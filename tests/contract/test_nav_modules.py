'导航模块化 · 契约测试\n\n用户口径：左侧导航栏（.nav / #nav）里的每一项=模块。本切片把 登录(账号)/管理/流量\n升为导航模块。防回退点：\n- PAGES 注册三个新模块；\n- page-netstats 磁贴容器 + switchPage 钩子（切页才拉数据）；\n- 侧栏旧按钮/旧卡片移除（不留死元素）；\n- /api/logout 路由存在（POST）；\n- api_self 未登录时返回 logged_in=false（账号页据此显示未登录态而不是报错）。'









from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"src"/"webui"))
import web

WEB = Path(__file__).resolve().parents[2] / "src" / "webui" / "web.py"


def src():
    root = WEB.parent
    return "\n".join([*(p.read_text() for p in sorted((root/"static").rglob("*.js"))),
                       (root/"templates"/"index.html").read_text(), WEB.read_text()])


def test_nav_registers_three_new_modules():
    
    s = src()
    pages_seg = s[s.index("const PAGES"):s.index("];", s.index("const PAGES"))]
    for entry in ("['login','','账号']",
                  "['extensions','','管理']",
                  "['netstats','','流量']"):
        assert entry not in pages_seg, f"这三个模块不应再出现在导航 {entry}"
    # 设置页必须有三个入口
    for jump in ("switchPage('login')", "switchPage('extensions')", "switchPage('netstats')"):
        assert jump in s, f"设置页缺入口 {jump}"
    # 手机更多面板必须补回 管理/流量（否则手机端无入口）
    assert "const extra = [['extensions','','管理'],['netstats','','流量']];" in s


def test_netstats_page_and_switch_hook():
    s = src()
    assert 'id="page-netstats"' in s and 'id="netgrid"' in s
    assert "APP.pages.register('netstats'" in s
    assert "APP.pages.register('login'" in s
    # 磁贴渲染目标 = #netgrid（旧侧栏小卡片已废除）
    assert "document.getElementById('netgrid')" in s


def test_sidefoot_legacy_elements_removed():
    s = src()
    assert 'id="netstats"' not in s, "侧栏旧流量卡片应移除（改为导航流量页）"
    assert "onclick=\"showLogin()\"" not in s, "侧栏旧登录按钮应移除（改为导航账号模块）"


def test_logout_endpoint_wired():
    s = src()
    assert "def api_logout():" in s
    assert "/api/logout" in web.ApiRouter({}).allowed("POST")
    assert "async function doLogout()" in s


def test_api_self_logged_in_flag():
    s = src()
    assert '"logged_in": False' in s
    assert 's["logged_in"] = True' in s


def test_acct_details_cached_not_per_call():
    """loadSelf 每 5s 打一次 /api/self：扩充字段必须有 10 分钟缓存，不许每次多打 VRChat。"""
    s = src()
    assert "_ACCT_CACHE" in s and "< 600" in s
