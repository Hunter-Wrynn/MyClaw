from __future__ import annotations

import contextlib
import datetime as dt
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


deploy = module("myclaw_deploy", "scripts/deploy.py")
privacy = module("myclaw_privacy", "scripts/check_privacy.py")
weekly = module("myclaw_weekly", "workspace/skills/weekly-domain-paper-review/scripts/run_codex_weekly.py")
hf = module("myclaw_hf", "workspace/skills/hf-daily/scripts/fetch_hf_daily.py")


def sample_values(directory: Path) -> dict[str, str]:
    return {
        "FEISHU_APP_ID": "cli_example",
        "FEISHU_APP_SECRET": 'example_secret_with_"quotes"_$and_backticks`',
        "FEISHU_CHAT_ID": "oc_" + "a" * 32,
        "FEISHU_OWNER_OPEN_ID": "ou_" + "b" * 32,
        "MYCLAW_STATE_DIR": str(directory / "state"),
        "MYCLAW_WORKSPACE": str(directory / "installed workspace"),
    }


def valid_weekly_report() -> str:
    lines = ["# 专题论文周报：Model Reuse / Model Routing / Model Selection", "",
             "> 统计区间：2026-08-31 至 2026-09-06（含首尾日期）", "",
             "## 一、本期专题概览", ""]
    lines.extend(f"- **维度 {i}**：这是用于校验结构的本地测试描述。" for i in range(7))
    lines.extend(["", "## 二、精选论文", ""])
    for number in range(1, 4):
        lines.append(f"### Test paper {number}")
        lines.append("- **核心方法**：" + "本地测试样本不包含实际论文事实。" * 50)
    lines.extend(["", "## 三、重点论文精读推荐", ""])
    for number in range(1, 4):
        lines.extend([f"### {number}. Test paper {number}", "用于本地格式验证。"])
    lines.extend(["", "## 四、关键词趋势", ""])
    lines.extend(f"- **Keyword {i}**：用于本地格式校验。" for i in range(12))
    lines.extend(["", "## 五、组内讨论问题", ""])
    lines.extend(f"{i}. 这是一个本地测试问题？" for i in range(1, 6))
    lines.extend(["", "## 六、检索说明", "纯合成本地测试，不是实际研究报告。", ""])
    return "\n".join(lines)


class DeploymentTests(unittest.TestCase):
    def test_json_render_preserves_secret_and_owner_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            options = deploy.settings(sample_values(Path(directory)), prompt=False)
            config = deploy.build_config(options, "test-gateway-token")
            parsed = json.loads(json.dumps(config, ensure_ascii=False))
            self.assertEqual(parsed["channels"]["feishu"]["appSecret"], options["FEISHU_APP_SECRET"])
            self.assertEqual(parsed["channels"]["feishu"]["groupSenderAllowFrom"], [options["FEISHU_OWNER_OPEN_ID"]])
            self.assertIsInstance(parsed["gateway"]["port"], int)
            self.assertEqual(parsed["gateway"]["bind"], "loopback")
            self.assertNotIn("{{", json.dumps(parsed))
            self.assertEqual(parsed["agents"]["defaults"]["model"]["primary"], "openai/gpt-5.6-sol")

    def test_env_is_data_not_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "shell-must-not-run"
            env_file = Path(directory) / "settings.env"
            payload = f"$(touch {marker})"
            env_file.write_text(f"FEISHU_APP_SECRET='{payload}'\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertEqual(deploy.load_env(env_file)["FEISHU_APP_SECRET"], payload)
            self.assertFalse(marker.exists())

    def test_missing_owner_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            values = sample_values(Path(directory))
            del values["FEISHU_OWNER_OPEN_ID"]
            with self.assertRaises(deploy.DeployError):
                deploy.settings(values, prompt=False)

    def test_runtime_inside_repository_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            values = sample_values(Path(directory))
            values["MYCLAW_WORKSPACE"] = str(ROOT / "private-runtime")
            with self.assertRaises(deploy.DeployError):
                deploy.settings(values, prompt=False)

    def test_private_config_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "local.json"
            deploy.private_write(path, "{}\n")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_dry_run_makes_no_files_or_tool_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            values = sample_values(Path(directory))
            output = io.StringIO()
            with mock.patch.dict(os.environ, values), mock.patch.object(sys, "argv", ["deploy.py", "--dry-run"]), mock.patch.object(deploy, "run") as execute, contextlib.redirect_stdout(output):
                self.assertEqual(deploy.main(), 0)
            execute.assert_not_called()
            self.assertEqual(list(Path(directory).iterdir()), [])
            self.assertNotIn(values["FEISHU_APP_SECRET"], output.getvalue())
            self.assertNotIn(values["FEISHU_CHAT_ID"], output.getvalue())

    def test_existing_instance_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            values = sample_values(Path(directory))
            state = Path(values["MYCLAW_STATE_DIR"])
            state.mkdir()
            config = state / "openclaw.json"
            original = '{"existing": true}\n'
            config.write_text(original)
            with mock.patch.dict(os.environ, values), mock.patch.object(sys, "argv", ["deploy.py", "--non-interactive"]), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(deploy.main(), 1)
            self.assertEqual(config.read_text(), original)

    def test_jobs_are_idempotent_and_use_installed_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            options = deploy.settings(sample_values(Path(directory)), prompt=False)
            records: list[dict] = []
            calls: list[list[str]] = []

            def fake_run(argv, env, **kwargs):
                calls.append(argv)
                if argv[1:3] == ["cron", "list"]:
                    return json.dumps({"jobs": records})
                if argv[1:3] == ["cron", "add"]:
                    name = argv[argv.index("--name") + 1]
                    record = {"id": f"test-job-{len(records)}", "name": name}
                    records.append(record)
                    return json.dumps(record)
                return "{}"

            with mock.patch.object(deploy, "run", side_effect=fake_run), contextlib.redirect_stdout(io.StringIO()):
                deploy.sync_jobs("openclaw", {}, options, "/usr/bin/python3", "/opt/bin/codex")
                deploy.sync_jobs("openclaw", {}, options, "/usr/bin/python3", "/opt/bin/codex")
            self.assertEqual(len(records), 7)
            adds = [call for call in calls if call[1:3] == ["cron", "add"]]
            self.assertEqual(len(adds), 7)
            commands = [call for call in calls if "--command-argv" in call]
            self.assertEqual(len(commands), 14)
            for command in commands:
                argv = json.loads(command[command.index("--command-argv") + 1])
                self.assertEqual(argv[0], "/usr/bin/python3")
                self.assertTrue(argv[1].startswith(str(options["workspace"])))
                self.assertTrue(Path(argv[1]).is_relative_to(options["workspace"]))
                self.assertEqual(command[command.index("--to") + 1], "chat:" + options["FEISHU_CHAT_ID"])
                self.assertNotIn("--command", command)

    def test_duplicate_job_aborts(self):
        with tempfile.TemporaryDirectory() as directory:
            options = deploy.settings(sample_values(Path(directory)), prompt=False)
            name = deploy.schedules()[0]["name"]
            data = {"jobs": [{"id": "a", "name": name}, {"id": "b", "name": name}]}
            with mock.patch.object(deploy, "run", return_value=json.dumps(data)), self.assertRaises(deploy.DeployError):
                deploy.sync_jobs("openclaw", {}, options, "/usr/bin/python3", "/opt/bin/codex")


class PrivacyTests(unittest.TestCase):
    def test_real_identifiers_and_auth_detected(self):
        text = json.dumps({"to": "oc_" + "f" * 32, "user": "ou_" + "b" * 32, "access_" + "token": "private-token-value"})
        self.assertGreaterEqual(len(privacy.inspect_text(text)), 2)

    def test_templates_are_placeholders(self):
        for path in (ROOT / "templates").glob("*.json"):
            self.assertEqual(privacy.inspect_text(path.read_text()), [])

    def test_local_secret_comparison_does_not_include_generic_model(self):
        values = privacy.private_values({"appSecret": "private-value", "model": "gpt-5.6-sol"})
        self.assertEqual(values, {"private-value"})
        self.assertEqual(privacy.inspect_text("a private-value leak", values), ["与本机私密配置值一致"])

    def test_staged_bytes_are_checked_instead_of_worktree(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            path = repo / "staged.txt"
            path.write_text("oc_" + "a" * 32)
            subprocess.run(["git", "add", "staged.txt"], cwd=repo, check=True)
            path.write_text("clean worktree")
            self.assertTrue(privacy.scan(repo, staged=True))


class RunnerTests(unittest.TestCase):
    def test_weekly_format_repair_and_failure_artifact(self):
        valid = valid_weekly_report()
        invalid = valid.replace("## 二、精选论文", "## 二、论文清单")
        with tempfile.TemporaryDirectory() as directory:
            replies = [(invalid, {}, "", 1.0), (valid, {}, "", 1.0)]
            output = io.StringIO()
            with mock.patch.object(weekly, "run_codex", side_effect=replies) as generate, mock.patch.object(weekly, "FAILURE_ARTIFACT_DIR", directory), mock.patch.object(sys, "argv", ["runner", "--preset", "monday-routing", "--start", "2026-08-31", "--end", "2026-09-06"]), contextlib.redirect_stdout(output):
                self.assertEqual(weekly.main(), 0)
            self.assertEqual(output.getvalue().strip(), valid.strip())
            self.assertFalse(generate.call_args.kwargs["enable_search"])
            self.assertEqual(len(list(Path(directory).glob("*.md"))), 1)
            self.assertEqual(next(Path(directory).glob("*.md")).read_text().strip(), invalid.strip())

    def test_unrepairable_report_never_reaches_stdout(self):
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with mock.patch.object(weekly, "run_codex", return_value=("invalid draft", {}, "", 1.0)) as generate, mock.patch.object(weekly, "FAILURE_ARTIFACT_DIR", directory), mock.patch.object(sys, "argv", ["runner", "--preset", "monday-routing"]), contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(weekly.main(), 1)
            self.assertEqual(output.getvalue(), "")
            self.assertEqual(generate.call_count, 3)
            self.assertEqual(len(list(Path(directory).glob("*.md"))), 3)

    def test_previous_complete_week(self):
        self.assertEqual(weekly.previous_complete_week(dt.date(2026, 10, 12)), (dt.date(2026, 10, 5), dt.date(2026, 10, 11)))

    def test_hf_official_abstract_fallback(self):
        paper = hf.Paper(1, "2601.12345", "Synthetic Test Paper", "We propose a reusable method for efficient modeling. Experiments demonstrate improvements on a public evaluation.", ("Test Author",), None)
        report = hf.fallback_report([paper], dt.date(2026, 1, 2), 1)
        hf.validate_report(report, [paper], dt.date(2026, 1, 2), 1)
        self.assertIn("官方英文摘要", report)
        self.assertNotIn("![", report)


if __name__ == "__main__":
    unittest.main()
