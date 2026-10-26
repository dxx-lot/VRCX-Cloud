# 贡献指南

报告问题时提供复现步骤、预期行为、版本和脱敏日志。不要上传配置、会话、数据库、密码、私钥或真实好友资料。

## 开发与验证

使用 Python 运行依赖、`requirements-dev.txt` 和 Node.js：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-frozen.txt -r requirements-dev.txt
PYTHON=.venv/bin/python NODE=node scripts/test.sh
```

浏览器布局与交互检查使用合成数据：

```sh
.venv/bin/python -m pip install playwright
.venv/bin/python -m playwright install chromium
.venv/bin/python scripts/check-mobile-browser.py
.venv/bin/python scripts/check-application-browser.py
```

结果写入被忽略的 `artifacts/`。测试使用替身或临时目录，不对真实好友执行写操作。

## 结构与约定

- `run.py`、`src/application/` 管理统一入口、私有目录和隔离的账号进程。
- `src/webui/static/core/` 管理账号上下文、资源、任务、缓存与页面生命周期。
- `src/webui/static/pages/` 实现交互，业务读写统一走 `gGet/gPost`。
- `src/webui/services/` 与 `backend/` 提供服务和领域逻辑，路由与账号转发共用白名单。

合并视角禁止写入，不能只靠隐藏按钮限制操作。异步任务绑定页面和账号代次，过期回复不得覆盖当前界面。缓存、图片与详情保留来源，延迟保存捕获操作开始时的账号。

新增行为应包含能够复现故障或竞态的测试。VRChat 协议和术语参考 `UPSTREAM_BASE_SHA` 固定的 VRCX 版本，保留第三方声明，不猜测端点或 HTTP 方法。

## 版本与源码包

版本号维护在根目录 `VERSION`。运行 `python3 scripts/export-public.py` 生成包含源码、测试、许可与校验清单的服务器源码包。解压后运行 `run.py --check` 和测试验证。不要把运行数据、个人配置或旧发行二进制加入源码仓库。

服务器工作流仅进行验证并上传构建附件，不自动公开发行版本。当前仓库提供服务器源码与容器部署材料，不提供桌面程序构建任务。贡献适用 [许可说明](LICENSING.md)。
