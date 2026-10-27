#!/usr/bin/env bash
# Prepare an isolated installation; application data stays outside the source.
set -euo pipefail

install_dir=''
no_start=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --dir)
            [ "$#" -ge 2 ] && [ -n "$2" ] || { echo '--dir 后面需要安装目录。' >&2; exit 2; }
            install_dir=$2; shift 2 ;;
        --no-start) no_start=1; shift ;;
        -h|--help)
            echo '用法：bash install-linux.sh [--dir 安装目录] [--no-start]'
            echo '支持 Ubuntu / Debian，使用 Python 3.10+ 的独立环境。'
            echo '默认下载安装到 ~/VRCX-Cloud；从源码目录运行时直接安装当前源码。'
            echo '--no-start 仅安装依赖，不设置密码、不启动程序。'
            exit 0 ;;
        *) printf '未知参数：%s\n' "$1" >&2; exit 2 ;;
    esac
done

fail() { printf '安装未完成：%s\n' "$1" >&2; exit 1; }
[ "$(uname -s)" = Linux ] || fail '此安装向导仅支持 Ubuntu / Debian Linux。'
[ -r /etc/os-release ] || fail '找不到 /etc/os-release，无法确认系统。'
# This is the operating system's standard identity file.
. /etc/os-release
case "${ID:-}" in ubuntu|debian) ;; *) fail '目前只支持 Ubuntu / Debian，请使用手动安装说明。' ;; esac

script_dir=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
if [ -f "$source_dir/run.py" ] && [ -f "$source_dir/requirements-frozen.txt" ] && [ -f "$source_dir/scripts/start-linux.sh" ]; then
    [ -z "$install_dir" ] || fail '已在源码目录运行，无需 --dir；不会复制或覆盖另一目录。'
else
    source_dir=''
    install_dir=${install_dir:-"$HOME/VRCX-Cloud"}
    [ ! -e "$install_dir" ] && [ ! -L "$install_dir" ] || fail "目录已存在，未覆盖：$install_dir；已有安装请运行该目录下的 scripts/start-linux.sh。"
fi

printf '\n[1/4] 检查系统依赖\n'
if ! command -v git >/dev/null 2>&1 || ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import venv, ensurepip' >/dev/null 2>&1; then
    if [ "$(id -u)" -eq 0 ]; then
        apt_command=(apt-get)
    elif command -v sudo >/dev/null 2>&1; then
        apt_command=(sudo apt-get)
    else
        fail '需要管理员安装 git、python3 和 python3-venv；当前用户没有 sudo。'
    fi
    "${apt_command[@]}" update
    "${apt_command[@]}" install -y git python3 python3-venv ca-certificates
fi
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)' || fail '需要 Python 3.10 或更新版本，请使用 Ubuntu 22.04+ / Debian 12+ 的系统 Python。'

printf '\n[2/4] 准备源码\n'
if [ -z "$source_dir" ]; then
    GIT_TERMINAL_PROMPT=0 git clone --depth 1 -- https://github.com/dxx-lot/VRCX-Cloud.git "$install_dir"
    source_dir=$(CDPATH= cd -- "$install_dir" && pwd)
fi
[ -f "$source_dir/run.py" ] && [ -f "$source_dir/scripts/start-linux.sh" ] || fail '源码不完整，请使用完整仓库或源码包。'

printf '\n[3/4] 安装独立 Python 环境\n'
[ ! -L "$source_dir/.venv" ] || fail '.venv 不能是符号链接，原目录未改动。'
if [ ! -e "$source_dir/.venv" ]; then
    python3 -m venv "$source_dir/.venv"
fi
venv_python="$source_dir/.venv/bin/python"
[ -x "$venv_python" ] || fail '现有 .venv 不完整，未删除或覆盖；请先检查该目录。'
"$venv_python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) and sys.prefix != sys.base_prefix else 1)' || fail '.venv 必须是 Python 3.10+ 的独立环境。'
"$venv_python" -m pip install --disable-pip-version-check 'pip @ https://files.pythonhosted.org/packages/3f/06/3e4420302363fbb71be3c7f35ce042f54bfca330e3e66b3a2e3c4cca579f/pip-26.2.2-py3-none-any.whl#sha256=fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70'
"$venv_python" -m pip install --disable-pip-version-check -r "$source_dir/requirements-frozen.txt"
"$venv_python" -B "$source_dir/run.py" --check

printf '\n[4/4] 安装完成\n源码目录：%s\n以后启动：bash %q\n' "$source_dir" "$source_dir/scripts/start-linux.sh"
if [ "$no_start" -eq 1 ]; then
    echo '尚未设置访问密码或启动程序；首次运行上面的启动命令会显示向导。'
    exit 0
fi
exec bash "$source_dir/scripts/start-linux.sh"
