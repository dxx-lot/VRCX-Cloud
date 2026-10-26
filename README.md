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

## 快速开始

服务器需要 Python 3.10 或更新版本。建议使用受支持的安全版本；运行不需要 Node.js 或前端构建步骤。下载本仓库源码，在源码目录执行：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-frozen.txt
.venv/bin/python run.py --check
.venv/bin/python run.py
```

在服务器本机打开 `http://127.0.0.1:8080/`，进入“账号”完成 VRChat 登录。账号未登录或登录失败时显示“登录异常”，两个账号分别管理。网页支持密码管理器和验证码自动填充；不保存 VRChat 明文密码，后续访问复用登录会话。

Ctrl+C 停止本次启动的服务，运行数据保留。Linux 默认数据目录为 `$XDG_DATA_HOME/vrcx-cloud`，未设置时为 `~/.local/share/vrcx-cloud`；可使用 `--data-dir /path/to/private-data` 指定私有目录。会话、配置、数据库和日志不得提交到仓库。

## 局域网与互联网访问

先设置应用访问密码，再开放局域网监听：

```sh
.venv/bin/python run.py --set-password
.venv/bin/python run.py --host 0.0.0.0
```

局域网设备访问 `http://服务器局域网地址:8080/`，用户名为 `vrcx`，密码为刚设置的应用访问密码。应用访问密码与 VRChat 密码分别管理。同一入口的口令对局域网和互联网同样生效，不会自动按网络免密；需要不同口令时应配置独立访问网关。

互联网访问需由部署者配置 HTTPS 反向代理和网络入口。**本项目不包含公网防护体系或公网安全运营服务。** 证书、防火墙、WAF、DDoS 防护和安全维护由部署者负责；HTTP 不加密流量，不能直接公开内部账号端口。

完整的 Python、容器、常驻运行和备份步骤见 [服务器部署](server/README.md)，安全边界见 [安全说明](SECURITY.md)。

## 许可与致谢

本项目参考并包含衍生自 [VRCX](https://github.com/vrcx-team/VRCX) 的实现，上游 MIT 版权及许可原文保留在 [第三方许可](LICENSES/VRCX-LICENSE)，来源和修改范围见 [第三方声明](LICENSES/NOTICE.md)。

本项目原创贡献和有权许可的修改采用**禁止商用、修改版公开源码**的自定义源码可见许可，见 [LICENSE](LICENSE) 和 [许可说明](LICENSING.md)。它不是 OSI 认可的开源许可，不取消第三方 MIT 许可已授予的权利。第三方项目名称用于标识来源和兼容关系，不代表关联或背书，也不授予其商标权。

参与贡献与运行合成测试见 [贡献指南](CONTRIBUTING.md)。
