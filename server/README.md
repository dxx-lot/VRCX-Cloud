# 服务器部署

VRCX Cloud 在服务器运行，手机和电脑通过浏览器访问。以下说明适用于本仓库的统一应用入口。

## 推荐：安装向导

Ubuntu 22.04、24.04 / Debian 12、13 用户先按 [首页安装步骤](../README.md#安装ubuntu--debian) 操作。向导自动下载源码、安装 Python 独立环境和依赖，首次启动选择访问方式、端口并设置密码；之后运行 `bash ~/VRCX-Cloud/scripts/start-linux.sh`。

已有源码时，在源码根目录运行 `bash scripts/install-linux.sh`。仅安装依赖、不启动或设置密码：`bash scripts/install-linux.sh --no-start`。独立下载安装时可用 `--dir /path/to/new-directory` 指定新的安装目录；不会覆盖已有目录。依赖安装失败时会停止，不会修改已有账号数据或重启其他安装。

启动向导把监听方式和端口保存在源码目录 `.vrcx-cloud/launch.json`，该目录已被 Git 忽略；它不包含访问密码。访问密码仍由应用保存为私有数据目录中的派生值。修改设置用 `bash scripts/start-linux.sh --configure`，只读检查用 `bash scripts/start-linux.sh --check`。

| 访问范围 | 程序监听和访问方式 |
|---|---|
| 本机 | 默认监听 `127.0.0.1:8080`，在同一台电脑访问 |
| 局域网 | 设置应用访问密码后使用 `--host 0.0.0.0`，其他设备访问服务器的局域网地址 |
| 互联网 | 由部署者配置域名、HTTPS 反向代理和网络入口；手机或电脑通过 HTTPS 地址访问 |

**本项目不包含公网防护体系或公网安全运营服务。** 应用访问密码、账号隔离、跨站写入检查和有限的失败请求节流属于应用基础控制，不代替 HTTPS 网关、主机防火墙、WAF、DDoS 防护、入侵监测或安全维护。互联网入口、证书、访问限制及外部防护由部署者负责配置和维护。监听全部接口不代表已自动开放路由器、云安全组或防火墙，也不保证互联网可达。

## 访问口令与部署方式

应用访问密码与 VRChat 账号密码分别管理。同一个应用入口不会按局域网或互联网自动切换口令；两者需要不同口令时，应配置两个独立网关。局域网也应设置访问保护，HTTP 不加密口令或个人资料。

## Python 部署

以下是手动方式；已完成安装向导的用户无需重复执行。

使用 Python 3.10 或更新版本，在源码目录创建独立环境：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-frozen.txt
.venv/bin/python run.py --check
.venv/bin/python run.py --data-dir /path/to/private-data --set-password
.venv/bin/python run.py --data-dir /path/to/private-data --host 0.0.0.0
```

从局域网设备打开 `http://服务器局域网地址:8080/`。访问用户名为 `vrcx`，密码是刚设置的应用访问密码，与 VRChat 密码不同。HTTP 不加密；需要加密连接时使用 HTTPS 入口。

## 远程服务器第一次访问

如果安装在云服务器并选择向导选项 `1`，程序只监听服务器本机。保留运行程序的 SSH 窗口；在**你自己电脑**的终端另开一个窗口，执行：

```sh
ssh -N -L 18080:127.0.0.1:8080 登录用户名@服务器地址
```

将 `登录用户名@服务器地址` 换成你平时 SSH 登录这台服务器所用的内容；网页端口如果不是 `8080`，把命令中最后的 `8080` 换成向导设置的端口。这个命令运行后保持窗口打开，没有输出是正常的。

然后在自己电脑的浏览器打开 `http://127.0.0.1:18080/`。访问用户名 `vrcx`，密码为应用访问密码；进入页面再登录 VRChat。SSH 隧道只供这台电脑使用，手机直接访问需要下方 HTTPS 入口。无需为此在云安全组放行应用的 `8080` 端口。

## 容器部署

在独立源码包根目录操作。`server/compose.yaml` 默认只把入口发布到宿主机回环地址：

```sh
docker compose -f server/compose.yaml build
docker compose -f server/compose.yaml run --rm app --set-password
docker compose -f server/compose.yaml up -d
```

数据保存于 Docker 命名卷 `vrcx-cloud-data`，默认以非 root 用户运行。必须先设置密码，否则容器拒绝开放监听。

局域网使用：编辑 `server/compose.yaml`，将端口映射的 `127.0.0.1:8080:8080` 改为 `0.0.0.0:8080:8080`，按需配置主机防火墙后重新创建容器。不要在镜像或 Git 中保存数据卷、会话或密码。

## 互联网 HTTPS 入口

保持应用入口仅供本机代理访问。以下 Caddy 示例需要替换域名，安装和运行 Caddy 由部署者完成：

```caddyfile
vrcx.example.com {
    reverse_proxy 127.0.0.1:8080 {
        flush_interval -1
    }
}
```

应用不依赖外部 Host 名称，代理应正常保留 `Host`；不要删除浏览器的 `Authorization` 或伪造 `Origin`。实时连接需要保持流式传输，Nginx 等代理需关闭响应缓冲并设置足够的读超时。仅开放 HTTPS 入口，内部两个账号端口始终留在本机，不能转发到外网。

本示例仅说明接入方式，不包含公网防护配置。DNS、证书签发条件、路由器端口映射、云安全组及防火墙按部署环境自行配置。可选择 VPN 或访问网关限制入口，避免将私人好友资料提供给无关人员。

## 运行、更新与备份

保持程序常驻需要部署者选择自己的服务管理工具。前台运行按 Ctrl+C 停止；容器使用 `docker compose -f server/compose.yaml stop`。先停止应用，再备份完整私有数据目录或数据卷。更新程序替换源码或镜像，不覆盖数据。恢复时保留账号A、账号B的独立目录。

发行包仅用于新环境安装，不会自动迁移或重启已有部署。首次进入网页后由用户本人登录 VRChat，项目不会附带任何账号或会话。

## 常见安装问题

| 提示或现象 | 处理 |
|---|---|
| `curl: command not found` | `sudo apt-get update && sudo apt-get install -y curl`；root 去掉 sudo |
| 没有 sudo 权限 | 先请管理员安装 `git python3 python3-venv ca-certificates`，再以自己的用户运行向导 |
| Python 版本不足 | 使用 Ubuntu 22.04、24.04 或 Debian 12、13 的系统 Python；向导不添加第三方软件源 |
| 输入密码没有字符显示 | 这是正常行为，输入至少 12 个字符后回车，再确认一次 |
| `Address already in use` | 原端口被占用，重新运行启动命令并加 `--configure`，换一个端口；不需要结束别人的程序 |
| 手机打不开 `127.0.0.1` | 它指手机自己；局域网用小主机 IP，云服务器用 HTTPS 入口 |
| 关闭 SSH 后网页停止 | 向导默认前台运行；需要常驻时使用容器部署或自行配置服务管理 |
| pip 下载失败 | 检查服务器到 Python 包源的网络，问题排除后在现有源码目录重新运行安装脚本；不要删除私有数据目录 |
