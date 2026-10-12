#!/usr/bin/env python3
"""Install this portable OpenClaw push setup without exporting credentials."""

from __future__ import annotations

import argparse
import datetime as dt
import getpass
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


REPO = Path(__file__).resolve().parents[1]
REQUIRED = (
    "FEISHU_APP_ID",
    "FEISHU_APP_SECRET",
    "FEISHU_CHAT_ID",
    "FEISHU_OWNER_OPEN_ID",
)
PLACEHOLDER = re.compile(r"\{\{([A-Z_]+)\}\}")


class DeployError(RuntimeError):
    pass


def load_env(path: Path) -> dict[str, str]:
    """Parse key=value as data, never as executable shell code."""
    values: dict[str, str] = {}
    if path.exists():
        for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.partition("=")
            key = key.strip()
            if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
                raise DeployError(f"环境文件第 {number} 行不是有效的 KEY=value")
            value = value.strip()
            if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
                value = value[1:-1]
            values[key] = value
    values.update(os.environ)
    return values


def settings(values: dict[str, str], *, prompt: bool) -> dict[str, Any]:
    result: dict[str, Any] = dict(values)
    for key in REQUIRED:
        value = result.get(key, "")
        if not value or value.startswith("YOUR_"):
            if not prompt:
                raise DeployError(f"请在 .env 中填写 {key}")
            result[key] = getpass.getpass(f"{key}（输入隐藏）: ").strip()
    checks = {
        "FEISHU_APP_ID": r"cli_[A-Za-z0-9]+",
        "FEISHU_CHAT_ID": r"oc_[a-fA-F0-9]{32}",
        "FEISHU_OWNER_OPEN_ID": r"ou_[a-fA-F0-9]{32}",
    }
    for key, pattern in checks.items():
        if not re.fullmatch(pattern, result[key]):
            raise DeployError(f"{key} 格式无效（飞书参数请使用机器人应用对应的 ID）")
    if not result["FEISHU_APP_SECRET"] or result["FEISHU_APP_SECRET"].startswith("YOUR_"):
        raise DeployError("FEISHU_APP_SECRET 不能为空或示例值")

    state = Path(result.get("MYCLAW_STATE_DIR") or Path.home() / ".openclaw").expanduser().resolve()
    workspace = Path(result.get("MYCLAW_WORKSPACE") or state / "workspace").expanduser().resolve()
    if workspace == REPO or workspace.is_relative_to(REPO) or state == REPO or state.is_relative_to(REPO):
        raise DeployError("运行数据和安装目录必须位于 Git 仓库之外")
    if workspace == Path("/") or state == Path("/"):
        raise DeployError("安装目录不能是文件系统根目录")
    model = result.get("MYCLAW_CODEX_MODEL") or "gpt-5.6-sol"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", model):
        raise DeployError("MYCLAW_CODEX_MODEL 应为模型名称，不含 provider/ 前缀")
    timezone = result.get("MYCLAW_TIMEZONE") or "Asia/Shanghai"
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise DeployError("MYCLAW_TIMEZONE 不是可用的 IANA 时区") from exc
    try:
        port = int(result.get("MYCLAW_GATEWAY_PORT") or "15110")
    except ValueError as exc:
        raise DeployError("MYCLAW_GATEWAY_PORT 必须为整数") from exc
    if not 1024 <= port <= 65535:
        raise DeployError("MYCLAW_GATEWAY_PORT 必须在 1024–65535 之间")
    result.update(state=state, workspace=workspace, model=model, timezone=timezone, port=port)
    return result


def render(value: Any, substitutions: dict[str, Any]) -> Any:
    """Substitute JSON values structurally so secrets cannot break JSON syntax."""
    if isinstance(value, dict):
        return {render(k, substitutions): render(v, substitutions) for k, v in value.items()}
    if isinstance(value, list):
        return [render(item, substitutions) for item in value]
    if not isinstance(value, str):
        return value
    match = PLACEHOLDER.fullmatch(value)
    if match:
        return substitutions[match.group(1)]
    return PLACEHOLDER.sub(lambda found: str(substitutions[found.group(1)]), value)


def build_config(options: dict[str, Any], token: str) -> dict[str, Any]:
    template = json.loads((REPO / "templates/openclaw.example.json").read_text(encoding="utf-8"))
    return render(template, {
        **{key: options[key] for key in REQUIRED},
        "WORKSPACE": str(options["workspace"]),
        "CODEX_MODEL": options["model"],
        "GATEWAY_PORT": options["port"],
        "GATEWAY_TOKEN": token,
    })


def schedules() -> list[dict[str, Any]]:
    return json.loads((REPO / "templates/schedules.example.json").read_text(encoding="utf-8"))


def run(argv: list[str], env: dict[str, str], *, timeout: int = 180) -> str:
    completed = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=timeout)
    if completed.returncode:
        # CLI output can contain secrets. Keep it off terminal/CI logs.
        raise DeployError(f"{Path(argv[0]).name} {argv[1]} 执行失败（退出码 {completed.returncode}）；请在本机检查工具状态")
    return completed.stdout


def json_output(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Some OpenClaw builds print plugin discovery logs before JSON.
        for index, character in enumerate(text):
            if character not in "{[":
                continue
            try:
                value = json.loads(text[index:])
                return value
            except json.JSONDecodeError:
                continue
    raise DeployError("OpenClaw 未返回有效 JSON；请检查版本是否匹配 versions.json")


def private_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)


def backup(path: Path, directory: Path) -> None:
    if path.exists():
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        destination = directory / path.name
        shutil.copy2(path, destination)
        destination.chmod(0o600)


def install_workspace(destination: Path, backup_directory: Path) -> None:
    source = REPO / "workspace"
    for path in sorted(source.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if path.is_symlink():
            raise DeployError("仓库 workspace 不允许符号链接")
        relative = path.relative_to(source)
        target = destination / relative
        if target.exists() and target.read_bytes() != path.read_bytes():
            backup(target, backup_directory / "workspace" / relative.parent)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def common_job_args(spec: dict[str, Any], options: dict[str, Any], python_bin: str, codex_bin: str) -> list[str]:
    workspace = options["workspace"]
    argv = [python_bin, str(workspace / spec["script"]), *spec["args"]]
    return [
        "--description", spec["description"],
        "--cron", spec["cron"], "--tz", options["timezone"], "--exact",
        "--session", "isolated", "--wake", "now",
        "--command-argv", json.dumps(argv, ensure_ascii=False),
        "--command-cwd", str(workspace),
        "--command-env", f"MYCLAW_WORKSPACE={workspace}",
        "--command-env", f"MYCLAW_CODEX_MODEL={options['model']}",
        "--command-env", f"MYCLAW_TIMEZONE={options['timezone']}",
        "--command-env", f"MYCLAW_CODEX_BIN={codex_bin}",
        "--timeout-seconds", str(spec["timeoutSeconds"]),
        "--no-output-timeout-seconds", str(spec["noOutputTimeoutSeconds"]),
        "--output-max-bytes", str(spec["outputMaxBytes"]),
        "--announce", "--channel", "feishu",
        "--to", f"chat:{options['FEISHU_CHAT_ID']}",
    ]


def sync_jobs(openclaw: str, env: dict[str, str], options: dict[str, Any], python_bin: str, codex_bin: str) -> None:
    listing = json_output(run([openclaw, "cron", "list", "--all", "--json"], env))
    existing = listing.get("jobs", [])
    for spec in schedules():
        matches = [job for job in existing if job.get("name") == spec["name"]]
        if len(matches) > 1:
            raise DeployError(f"发现重复任务 {spec['name']}；请先在本机处理重复项")
        common = common_job_args(spec, options, python_bin, codex_bin)
        if matches:
            command = [openclaw, "cron", "edit", matches[0]["id"], *common,
                       "--enable", "--no-best-effort-deliver", "--failure-alert",
                       "--failure-alert-after", "1", "--failure-alert-channel", "feishu",
                       "--failure-alert-to", f"chat:{options['FEISHU_CHAT_ID']}"]
        else:
            command = [openclaw, "cron", "add", "--name", spec["name"],
                       "--declaration-key", spec["name"], *common, "--json"]
        output = run(command, env)
        if not matches:
            added = json_output(output)
            job = added.get("job", added)
            job_id = job.get("id")
            if not job_id:
                raise DeployError("新增任务未返回 ID，无法启用失败提醒")
            run([openclaw, "cron", "edit", job_id, "--failure-alert",
                 "--failure-alert-after", "1", "--failure-alert-channel", "feishu",
                 "--failure-alert-to", f"chat:{options['FEISHU_CHAT_ID']}"], env)
        print(f"已同步任务：{spec['name']}")


def dependencies(options: dict[str, Any], *, install: bool) -> tuple[str, str, str]:
    versions = json.loads((REPO / "versions.json").read_text(encoding="utf-8"))
    if sys.version_info < (3, 11):
        raise DeployError("需要 Python 3.11+")
    node = shutil.which("node")
    npm = shutil.which("npm")
    if not node or not npm:
        raise DeployError("请先安装 Node.js 22.22.3+（或 24.15+）及 npm")
    node_text = run([node, "--version"], dict(os.environ)).strip().lstrip("v")
    node_version = tuple(int(part) for part in node_text.split(".")[:3])
    if node_version < (22, 22, 3) or node_version[0] == 23 or (node_version[0] == 24 and node_version < (24, 15, 0)):
        raise DeployError("Node.js 版本不满足要求；请使用 22.22.3+ 或 24.15+")
    if install:
        print("安装锁定版本的 OpenClaw 和 Codex CLI…")
        run([npm, "install", "-g", f"openclaw@{versions['openclaw']}", f"@openai/codex@{versions['codex']}"], dict(os.environ), timeout=600)
    openclaw = shutil.which("openclaw")
    codex = options.get("MYCLAW_CODEX_BIN") or shutil.which("codex")
    python = options.get("MYCLAW_PYTHON_BIN") or sys.executable
    if not openclaw or not codex or not os.access(codex, os.X_OK) or not os.access(python, os.X_OK):
        raise DeployError("找不到 openclaw/codex/python3；使用 --install-deps 或检查 PATH")
    openclaw_version = run([openclaw, "--version"], dict(os.environ))
    if versions["openclaw"] not in openclaw_version:
        raise DeployError("OpenClaw 版本不匹配，请安装 versions.json 中的版本")
    return openclaw, str(Path(codex).absolute()), str(Path(python).absolute())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=REPO / ".env")
    parser.add_argument("--dry-run", action="store_true", help="检查参数并显示计划，不写入、不登录、不发送")
    parser.add_argument("--install-deps", action="store_true", help="通过 npm 安装锁定版本的 OpenClaw/Codex")
    parser.add_argument("--update", action="store_true", help="允许备份并替换非 MyClaw 管理的现有配置")
    parser.add_argument("--non-interactive", action="store_true", help="缺少参数或 Codex 登录时立即失败")
    args = parser.parse_args()
    try:
        options = settings(load_env(args.env_file), prompt=not args.non_interactive and not args.dry_run)
        config_path = options["state"] / "openclaw.json"
        marker = options["state"] / "myclaw" / "installation.json"
        if config_path.exists() and not marker.exists() and not args.update:
            raise DeployError("此目录已有 OpenClaw 配置。请选择 MYCLAW_STATE_DIR/MYCLAW_WORKSPACE，或使用 --update 备份后替换")
        if args.dry_run:
            print("参数检查通过。计划安装 3 个 Skills，注册/更新 7 个定时任务。")
            print("网关：仅本机访问；飞书：WebSocket；群聊：仅允许配置的用户 @ 触发。")
            for spec in schedules():
                print(f"{spec['name']}: {spec['cron']} ({options['timezone']})")
            return 0

        openclaw, codex, python = dependencies(options, install=args.install_deps)
        env = dict(os.environ)
        env.update(OPENCLAW_STATE_DIR=str(options["state"]), OPENCLAW_CONFIG_PATH=str(config_path))
        login = subprocess.run([codex, "login", "status"], capture_output=True, text=True)
        if login.returncode:
            if args.non_interactive:
                raise DeployError("Codex 尚未登录，请先运行 codex login --device-auth")
            print("请使用你自己的 Codex 账号完成设备码登录。")
            if subprocess.call([codex, "login", "--device-auth"]):
                raise DeployError("Codex 登录未完成")

        previous: dict[str, Any] = {}
        if config_path.exists():
            previous = json.loads(config_path.read_text(encoding="utf-8"))
        token = previous.get("gateway", {}).get("auth", {}).get("token") or secrets.token_hex(32)
        timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup_directory = options["state"] / "myclaw" / "backups" / timestamp
        backup(config_path, backup_directory)
        private_write(config_path, json.dumps(build_config(options, token), ensure_ascii=False, indent=2) + "\n")
        install_workspace(options["workspace"], backup_directory)
        private_write(marker, json.dumps({"version": 1, "repository": "Hunter-Wrynn/MyClaw", "updatedAt": timestamp}) + "\n")

        # Install Feishu only if this OpenClaw distribution does not ship it.
        plugin_list = json_output(run([openclaw, "plugins", "list", "--json"], env))
        plugins = plugin_list.get("plugins", []) if isinstance(plugin_list, dict) else plugin_list
        if not any(plugin.get("id") == "feishu" for plugin in plugins):
            versions = json.loads((REPO / "versions.json").read_text(encoding="utf-8"))
            run([openclaw, "plugins", "install", f"@openclaw/feishu@{versions['feishu']}", "--pin"], env, timeout=600)
        run([openclaw, "config", "validate", "--json"], env)
        print("配置与 Skills 已安装；配置文件权限为 600。安装并启动网关…")
        run([openclaw, "gateway", "install", "--force", "--port", str(options["port"])], env)
        run([openclaw, "gateway", "restart"], env)
        sync_jobs(openclaw, env, options, python, codex)
        state = json_output(run([openclaw, "channels", "status", "--channel", "feishu", "--json"], env))
        accounts = state.get("channelAccounts", {}).get("feishu", [])
        if not any(account.get("connected") for account in accounts):
            raise DeployError("任务已注册，但飞书尚未连接。请完成飞书权限、事件订阅及应用发布后再检查 channels status")
        print("安装完成，飞书已连接；任务将在设定时间自动推送。")
        print("本次安装不会立即运行日报任务。")
        return 0
    except (DeployError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        # Do not expose exception details that may contain rendered config/secrets.
        message = str(exc) if isinstance(exc, DeployError) else f"安装失败（{type(exc).__name__}），请检查本机配置和依赖"
        print(message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
