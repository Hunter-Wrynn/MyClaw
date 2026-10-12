#!/usr/bin/env bash
set -euo pipefail
task_repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
  echo '请先安装 Python 3.11+，再执行安装。' >&2
  exit 1
fi
exec python3 "$task_repo_dir/scripts/deploy.py" "$@"
