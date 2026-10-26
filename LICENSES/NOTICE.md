# 第三方代码与声明

本项目参考并包含衍生自 [VRCX](https://github.com/vrcx-team/VRCX) 的实现，固定基线见根目录 `UPSTREAM_BASE_SHA`。`backend/` 与 `src/webui/` 包含衍生实现、服务器适配和功能修改。

VRCX 的 MIT 版权及许可全文原样保留在 [VRCX-LICENSE](VRCX-LICENSE)。其授予的原有权利继续有效，本项目非商用条件不能取消该授权。本项目原创贡献和有权许可的修改适用根目录 LICENSE，范围见 [PROJECT_SCOPE.md](PROJECT_SCOPE.md)。

修改涉及 Python 服务、浏览器界面、账号隔离、图片缓存、动态展示、移动端交互及应用启动。源码不包含完整的 VRCX Electron 应用；上游版本可从其仓库按固定提交取得。Python与运行依赖分别遵循各自许可。

本项目为非官方独立实现，与 VRChat Inc.、VRCX 开发团队没有隶属或背书关系。第三方名称仅用于标识来源或兼容关系；代码许可不授予第三方名称、标识或商标的权利。本项目图标为独立图案。
