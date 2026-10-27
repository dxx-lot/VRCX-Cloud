# VRCX Cloud

面向自托管服务器的 VRChat 好友动态与账号管理网页。服务器负责运行，电脑、平板和手机通过浏览器访问；无需在手机部署程序。当前版本为 **v1.0.0**，版本号见 [VERSION](VERSION)。

本项目是非官方独立项目，与 VRChat Inc.、VRCX 开发团队没有隶属或背书关系。

## 功能

- 好友动态、单人筛选、搜索与历史分页。
- 好友位置、世界和房间详情、图片缓存。
- 账号A和账号B的独立会话与数据目录，以及只读合并视角。
- 收藏、通知、模型、个人状态与好友管理。
- 适配手机的导航、返回、筛选和详情交互。
- 可选 Bark / Telegram 推送，默认关闭。

登录失效或采集异常时会显示状态。页面实时连接不可用时使用定时刷新；采集是否正常应查看上次采集时间。合并视角用于阅读，写入操作需选择单个账号。

## 安装：Ubuntu / Debian

支持 Ubuntu 22.04、24.04 和 Debian 12、13。**以下命令在准备运行程序的 Linux 服务器或小主机终端里执行，不是在手机里执行。** 云服务器先用 SSH 登录；建议使用普通用户，缺少系统依赖时脚本会请求 sudo 权限。

复制下面两行一起执行：

```sh
curl -fL https://raw.githubusercontent.com/dxx-lot/VRCX-Cloud/main/scripts/install-linux.sh -o install-vrcx-cloud.sh &&
bash install-vrcx-cloud.sh
```

脚本会自动下载源码到 `~/VRCX-Cloud`，准备 Python 独立环境、安装依赖，然后打开首次启动向导。无需手工激活环境，也无需 Node.js。若已下载并解压源码，在源码目录运行 `bash scripts/install-linux.sh` 即可。

如果提示 `curl: command not found`，先运行 `sudo apt-get update && sudo apt-get install -y curl`；root 用户去掉 `sudo`，然后重试。若源码目录已存在，脚本会停止，保留现有文件；已有安装直接使用下面的启动命令。

首次启动只需完成三件事：

1. 选择访问方式：输入 `1` 用于本机或云服务器；输入 `2` 用于家中局域网的手机、电脑访问。
2. 选择网页端口，不修改就直接回车，默认 `8080`。
3. 设置至少 12 个字符的应用访问密码，输入时终端不显示字符；两次输入保持一致。这不是 VRChat 密码。

向导会显示该用什么地址打开网页。网页访问用户名是 **`vrcx`**，密码是刚设置的应用访问密码；进入网页后，再到“账号”页登录 VRChat。以后启动会复用设置，不反复要求输入应用访问密码。

## 怎么打开、以后怎么启动

| 安装位置与选择 | 浏览器访问方式 |
|---|---|
| 同一台电脑，选择 `1` | 在这台电脑打开 `http://127.0.0.1:8080/` |
| 家中小主机，选择 `2` | 手机连同一局域网，打开向导显示的 `http://小主机局域网IP:8080/` |
| 云服务器，选择 `1` | 按向导显示的 SSH 隧道命令，从自己的电脑访问；要让手机直接通过互联网访问，需配置下方 HTTPS 入口 |

**远程服务器的 `127.0.0.1` 指服务器自身，不能直接填到手机浏览器里。** 云服务器通过 SSH 隧道访问的具体步骤见 [远程服务器第一次访问](server/README.md#远程服务器第一次访问)。

以后启动，只执行：

```sh
bash ~/VRCX-Cloud/scripts/start-linux.sh
```

重新选择访问方式或端口：`bash ~/VRCX-Cloud/scripts/start-linux.sh --configure`。重新设置应用访问密码：`bash ~/VRCX-Cloud/scripts/start-linux.sh --set-password`。如果安装在其他目录，将命令中的 `~/VRCX-Cloud` 换成安装结束时显示的源码目录。

当前向导为前台运行：按 Ctrl+C 或关闭运行终端会停止程序，数据保留；不会自动创建开机服务。需要后台常驻可选择 [容器部署](server/README.md#容器部署)。Linux 私有数据默认保存在 `~/.local/share/vrcx-cloud`；设置了 `XDG_DATA_HOME` 时在其下的 `vrcx-cloud` 目录。会话、配置、数据库和日志不得提交到仓库。

互联网访问需配置 HTTPS 反向代理和网络入口。**本项目不包含公网防护体系或公网安全运营服务。** 证书、防火墙与安全维护由部署者负责；安装脚本不会修改防火墙或开放云安全组，也不能把内部账号端口公开。完整手动安装、容器、HTTPS 和备份步骤见 [服务器部署](server/README.md)，安全边界见 [安全说明](SECURITY.md)。

## 许可与致谢

本项目参考并包含衍生自 [VRCX](https://github.com/vrcx-team/VRCX) 的实现，上游 MIT 版权及许可原文保留在 [第三方许可](LICENSES/VRCX-LICENSE)，来源和修改范围见 [第三方声明](LICENSES/NOTICE.md)。

本项目原创贡献和有权许可的修改采用 **MIT License**，允许商业使用、修改和分发；分发时须保留版权和许可声明。完整条款见 [LICENSE](LICENSE) 和 [许可说明](LICENSING.md)。第三方项目名称用于标识来源和兼容关系，不代表关联或背书，也不授予其商标权。

参与贡献与运行合成测试见 [贡献指南](CONTRIBUTING.md)。
