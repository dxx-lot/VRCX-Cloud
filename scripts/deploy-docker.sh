#!/usr/bin/env bash
set -euo pipefail

install_dir=''
requested_bind=''
requested_port=''
requested_project=''
action=deploy
fail() { printf 'Docker 部署未完成：%s\n' "$1" >&2; exit 1; }
while [ "$#" -gt 0 ]; do
    case "$1" in
        --dir|--bind|--port|--project)
            [ "$#" -ge 2 ] && [ -n "$2" ] || fail "$1 后面需要参数。"
            case "$1" in --dir) install_dir=$2 ;; --bind) requested_bind=$2 ;; --port) requested_port=$2 ;; --project) requested_project=$2 ;; esac
            shift 2 ;;
        --status|--logs|--stop|--start)
            [ "$action" = deploy ] || fail '一次只能选择一个管理操作。'
            action=${1#--}; shift ;;
        -h|--help)
            echo '用法：bash deploy-docker.sh [--dir 新目录] [--bind 127.0.0.1|0.0.0.0] [--port 8080] [--project 名称]'
            echo '已有部署：--status 查看状态；--logs 查看日志；--stop 停止并保留数据；--start 后台启动。'
            echo '需要已安装且当前用户可以访问的 Docker Engine 和 Compose v2。'
            exit 0 ;;
        *) fail "未知参数：$1" ;;
    esac
done

command -v docker >/dev/null 2>&1 || fail '未安装 Docker；请先按 https://docs.docker.com/engine/install/ 安装 Docker Engine 和 Compose 插件。'
docker compose version >/dev/null 2>&1 || fail '需要 Compose v2，请安装 Docker Compose 插件。'
docker info >/dev/null 2>&1 || fail '当前用户不能访问 Docker。请检查 Docker 服务和当前用户权限后重试。'
compose_help=$(docker compose up --help)
case "$compose_help" in *--wait*) ;; *) fail '当前 Compose 不支持等待健康检查，请更新 Compose v2。' ;; esac

script_dir=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
if [ -f "$source_dir/server/compose.yaml" ] && [ -f "$source_dir/run.py" ]; then
    [ -z "$install_dir" ] || fail '已从源码目录运行，无需 --dir。'
else
    install_dir=${install_dir:-"$HOME/VRCX-Cloud-docker"}
    if [ -e "$install_dir" ] || [ -L "$install_dir" ]; then
        [ ! -L "$install_dir" ] && [ -f "$install_dir/.vrcx-cloud/docker.env" ] && [ -f "$install_dir/server/compose.yaml" ] || fail "目录已存在且不是已登记的 Docker 安装，未覆盖：$install_dir"
    else
        [ "$action" = deploy ] || fail '还没有安装，请先执行部署命令。'
        if ! command -v git >/dev/null 2>&1; then
            fail '下载源码需要 git；Ubuntu/Debian 可运行 sudo apt-get update && sudo apt-get install -y git ca-certificates。'
        fi
        GIT_TERMINAL_PROMPT=0 git clone --depth 1 -- https://github.com/dxx-lot/VRCX-Cloud.git "$install_dir"
    fi
    source_dir=$(CDPATH= cd -- "$install_dir" && pwd)
fi
case "$source_dir" in *$'\n'*|*$'\r'*) fail '安装目录不能包含换行。' ;; esac
config_dir="$source_dir/.vrcx-cloud"
config_file="$config_dir/docker.env"
[ ! -L "$config_dir" ] || fail '配置目录不能是符号链接。'
if [ -e "$config_dir" ]; then
    [ -d "$config_dir" ] && [ -O "$config_dir" ] || fail '请使用原安装用户管理该目录。'
fi

bind_host=127.0.0.1
port=8080
project=vrcx-cloud
has_config=0
if [ -e "$config_file" ] || [ -L "$config_file" ]; then
    [ ! -L "$config_file" ] && [ "$(find "$config_file" -prune -type f -links 1 -print)" = "$config_file" ] || fail '配置必须是没有链接的普通文件。'
    seen_bind=0; seen_port=0; seen_project=0
    while IFS='=' read -r key value || [ -n "$key" ]; do
        case "$key" in
            VRCX_BIND_HOST) [ "$seen_bind" -eq 0 ] || fail '配置字段重复。'; bind_host=$value; seen_bind=1 ;;
            VRCX_PORT) [ "$seen_port" -eq 0 ] || fail '配置字段重复。'; port=$value; seen_port=1 ;;
            VRCX_PROJECT) [ "$seen_project" -eq 0 ] || fail '配置字段重复。'; project=$value; seen_project=1 ;;
            *) fail '配置字段无效，未执行。' ;;
        esac
    done < "$config_file"
    [ "$seen_bind$seen_port$seen_project" = 111 ] || fail 'Docker 启动配置不完整。'
    has_config=1
elif [ "$action" != deploy ]; then
    fail '尚未找到本目录的 Docker 部署配置。'
fi

if [ "$has_config" -eq 0 ] && [ -z "$requested_bind" ] && [ -t 0 ]; then
    echo '选择访问方式：1 本机/云服务器（默认）；2 家中局域网。'
    read -r -p '输入 1 或 2 [1]：' choice
    case "${choice:-1}" in 1) bind_host=127.0.0.1 ;; 2) bind_host=0.0.0.0 ;; *) fail '请选择 1 或 2。' ;; esac
fi
if [ "$has_config" -eq 0 ] && [ -z "$requested_port" ] && [ -t 0 ]; then
    read -r -p '网页端口 [8080]：' choice
    port=${choice:-8080}
fi
if [ "$has_config" -eq 1 ] && [ -n "$requested_project" ] && [ "$requested_project" != "$project" ]; then
    fail '已有部署的项目名已固定；新增独立项目请使用其他安装目录。'
fi
if [ "$action" != deploy ] && { [ -n "$requested_bind" ] || [ -n "$requested_port" ]; }; then
    fail '管理操作不修改端口或监听方式；修改设置请重新执行部署命令。'
fi
bind_host=${requested_bind:-$bind_host}
port=${requested_port:-$port}
project=${requested_project:-$project}
case "$bind_host" in 127.0.0.1|0.0.0.0) ;; *) fail '监听地址只支持 127.0.0.1 或 0.0.0.0。' ;; esac
[[ "$port" =~ ^[0-9]{1,5}$ ]] || fail '端口须为 1 到 65535 的整数。'
port=$((10#$port))
[ "$port" -ge 1 ] && [ "$port" -le 65535 ] || fail '端口须为 1 到 65535 的整数。'
[[ "$project" =~ ^[a-z0-9][a-z0-9_-]{0,62}$ ]] || fail '项目名仅支持小写字母、数字、下划线和连字符，最长63字符。'

container_ids=$(docker ps -aq --filter "label=com.docker.compose.project=$project")
while IFS= read -r container_id; do
    [ -n "$container_id" ] || continue
    owner=$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' "$container_id")
    [ "$owner" = "$source_dir/server" ] || [ "$owner" = "$source_dir" ] || fail '同名 Docker 项目属于其他目录，未停止或改动；请用 --project 指定其他名称。'
done <<< "$container_ids"
if [ "$has_config" -eq 0 ] && [ -z "$container_ids" ] && docker volume inspect "${project}_vrcx-cloud-data" >/dev/null 2>&1; then
    fail '同名数据卷已存在且没有本目录的部署登记，未接管；请检查原部署或使用其他 --project 名称。'
fi

if [ "$action" = deploy ]; then
    umask 077
    mkdir -p -- "$config_dir"
    chmod 700 "$config_dir"
    temporary=$(mktemp "$config_dir/.docker-env.XXXXXX")
    printf 'VRCX_BIND_HOST=%s\nVRCX_PORT=%s\nVRCX_PROJECT=%s\n' "$bind_host" "$port" "$project" > "$temporary"
    mv -f -- "$temporary" "$config_file"
fi
compose() {
    env VRCX_BIND_HOST="$bind_host" VRCX_PORT="$port" docker compose --env-file "$config_file" --project-directory "$source_dir/server" -p "$project" -f "$source_dir/server/compose.yaml" "$@"
}
case "$action" in
    status) compose ps app; exit 0 ;;
    logs) compose logs --tail 100 -f app; exit 0 ;;
    stop) compose stop app; echo '已停止本项目，数据卷保留。'; exit 0 ;;
    start) compose up -d --wait --wait-timeout 90 app ;;
    deploy)
        echo '[1/3] 构建 Docker 镜像'
        compose build app
        echo '[2/3] 检查应用访问密码'
        password_status=0
        compose run --rm -T --no-deps --entrypoint python app -c '
import sys
from pathlib import Path
from src.application.launcher import read_json
from src.application.gateway import valid_password_record
path=Path("/state/application.json")
if not path.exists() and not path.is_symlink(): sys.exit(3)
try:
    app=read_json(path)
    if app.get("schema") != 1: raise ValueError("invalid schema")
    if app.get("password") is None: sys.exit(3)
    if not valid_password_record(app.get("password")): raise ValueError("invalid password record")
except (OSError,ValueError):
    print("已有应用配置异常，未重设密码。",file=sys.stderr)
    sys.exit(1)
' || password_status=$?
        case "$password_status" in
            0) echo '复用已有应用访问密码。' ;;
            3)
                [ -t 0 ] || fail '首次部署需要交互式终端设置访问密码，请在服务器终端重试。'
                echo '首次部署：设置至少12个字符的应用访问密码，输入时不显示字符。'
                compose run --rm --no-deps app --set-password ;;
            *) fail '无法确认现有密码，未改动密码或启动服务。' ;;
        esac
        echo '[3/3] 后台启动并等待健康检查'
        compose up -d --wait --wait-timeout 90 app
        ;;
esac

printf '\n部署完成，已在后台运行；关闭终端不会停止。\n网页用户名：vrcx；密码：你设置的应用访问密码。\n数据卷：%s_vrcx-cloud-data\n' "$project"
if [ "$bind_host" = 127.0.0.1 ]; then
    printf '本机访问：http://127.0.0.1:%s/\n云服务器请在自己电脑建立隧道：\n  ssh -N -L 18080:127.0.0.1:%s 登录用户名@服务器地址\n然后打开 http://127.0.0.1:18080/；互联网手机访问需配置 HTTPS。\n' "$port" "$port"
else
    printf '局域网访问：http://服务器局域网IP:%s/；手机须连同一局域网。\n' "$port"
fi
printf '状态：bash %q --status\n日志：bash %q --logs\n停止：bash %q --stop\n启动：bash %q --start\n' "$source_dir/scripts/deploy-docker.sh" "$source_dir/scripts/deploy-docker.sh" "$source_dir/scripts/deploy-docker.sh" "$source_dir/scripts/deploy-docker.sh"
