#!/usr/bin/env bash
set -euo pipefail
if [ "${1:-}" = --help ] || [ "${1:-}" = -h ]; then
    echo '用法：bash scripts/start-linux.sh [--configure | --check | --set-password]'
    echo '首次启动选择访问方式并设置密码；以后启动复用配置。'
    echo '--configure 重新选择访问方式和端口；--check 只检查，不启动或改动数据。'
    exit 0
fi
[ "$(uname -s)" = Linux ] || { echo '此启动向导仅支持 Linux。' >&2; exit 1; }
script_dir=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
venv_python="$source_dir/.venv/bin/python"
[ -x "$venv_python" ] || { echo '请先运行 bash scripts/install-linux.sh 完成安装。' >&2; exit 1; }
cd -- "$source_dir"
exec "$venv_python" -B -m src.application.linux_setup "$@"
