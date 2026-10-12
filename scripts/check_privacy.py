#!/usr/bin/env python3
"""Check tracked/exportable files for credentials and personal identifiers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


REPO = Path(__file__).resolve().parents[1]
PATTERNS = {
    "飞书群/用户真实 ID": re.compile(r"\b(?:oc|ou)_[a-fA-F0-9]{32}\b"),
    "飞书真实 App ID": re.compile(r"\bcli_[a-fA-F0-9]{16}\b"),
    "API key/token": re.compile(r"\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    "JWT": re.compile(r"\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\b"),
    "私钥": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "登录 JSON 字段": re.compile(r'"(?:access_token|refresh_token|id_token)"\s*:\s*"[^"\s]{10,}"'),
}
FORBIDDEN_NAMES = {
    "auth.json", "auth-profiles.json", "config.toml", "openclaw.json",
    "jobs.json", ".env", "MEMORY.md", "USER.md", "IDENTITY.md",
}
FORBIDDEN_PARTS = {".codex", ".openclaw", "credentials", "sessions", "memory", ".artifacts", "backups"}


def file_paths(repo: Path, *, staged: bool = False) -> list[Path]:
    if staged:
        arguments = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"]
    else:
        arguments = ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
    output = subprocess.check_output(arguments, cwd=repo)
    return [Path(name) for name in dict.fromkeys(output.decode().split("\0")) if name]


def private_values(value: object, *, sensitive: bool = False) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            marked = sensitive or bool(re.search(r"secret|token|api.?key|app.?id|allow.?from|^to$|allowedOrigins", key, re.I))
            result.update(private_values(child, sensitive=marked))
    elif isinstance(value, list):
        for child in value:
            result.update(private_values(child, sensitive=sensitive))
    elif sensitive and isinstance(value, str) and len(value) >= 8:
        result.add(value)
    return result


def inspect_text(text: str, local_values: set[str] | None = None) -> list[str]:
    findings = [label for label, pattern in PATTERNS.items() if pattern.search(text)]
    if any(value in text for value in local_values or set()):
        findings.append("与本机私密配置值一致")
    return findings


def scan(repo: Path, *, local_values: set[str] | None = None, staged: bool = False) -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    for relative in file_paths(repo, staged=staged):
        if relative.name in FORBIDDEN_NAMES or any(part in FORBIDDEN_PARTS for part in relative.parts):
            findings.append((str(relative), "不允许提交的运行/登录文件"))
            continue
        path = repo / relative
        if path.is_symlink():
            findings.append((str(relative), "符号链接可能指向仓库外的私密文件"))
            continue
        if staged:
            payload = subprocess.check_output(["git", "show", f":{relative.as_posix()}"], cwd=repo)
        else:
            if not path.is_file():
                continue
            payload = path.read_bytes()
        try:
            content = payload.decode("utf-8")
        except UnicodeDecodeError:
            findings.append((str(relative), "导出仓库仅接受可检查的 UTF-8 文本文件"))
            continue
        for finding in inspect_text(content, local_values):
            findings.append((str(relative), finding))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compare-local", type=Path, help="额外对照本机私密 JSON，仅内存比较，不输出私密值")
    parser.add_argument("--staged", action="store_true", help="检查实际暂存内容，供 pre-commit 使用")
    args = parser.parse_args()
    local_values: set[str] = set()
    if args.compare_local:
        local_values = private_values(json.loads(args.compare_local.read_text(encoding="utf-8")))
    findings = scan(REPO, local_values=local_values, staged=args.staged)
    if findings:
        for name, finding in findings:
            print(f"{name}: {finding}", file=sys.stderr)
        print("隐私检查失败；仅输出位置和类型，未输出任何凭证值。", file=sys.stderr)
        return 1
    print("隐私检查通过：未发现登录数据、真实飞书标识或密钥。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
