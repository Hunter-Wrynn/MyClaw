#!/usr/bin/env python3
"""Validate the rendered template with installed OpenClaw in a temporary state."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from deploy import build_config, private_write, settings


def main() -> int:
    executable = shutil.which("openclaw")
    if not executable:
        print("请先安装 versions.json 中的 OpenClaw 版本。")
        return 1
    with tempfile.TemporaryDirectory(prefix="myclaw-schema-") as directory:
        base = Path(directory)
        options = settings({
            "FEISHU_APP_ID": "cli_example",
            "FEISHU_APP_SECRET": "example-validation-value",
            "FEISHU_CHAT_ID": "oc_" + "a" * 32,
            "FEISHU_OWNER_OPEN_ID": "ou_" + "b" * 32,
            "MYCLAW_STATE_DIR": str(base / "state"),
            "MYCLAW_WORKSPACE": str(base / "workspace"),
        }, prompt=False)
        config = options["state"] / "openclaw.json"
        private_write(config, json.dumps(build_config(options, "local-schema-test-token")))
        env = {**os.environ, "OPENCLAW_STATE_DIR": str(options["state"]), "OPENCLAW_CONFIG_PATH": str(config)}
        result = subprocess.run([executable, "config", "validate", "--json"], env=env,
                                capture_output=True, text=True, timeout=120)
        if result.returncode:
            print("OpenClaw 模板校验失败。")
            print(result.stdout or result.stderr)
            return 1
        print("OpenClaw 实际配置校验通过；使用了临时状态目录，未启动网关或注册任务。")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
