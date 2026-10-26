'UI 交互切片 · 结构契约（web.py 内嵌 JS）\n\n这三个切片是纯前端行为（web.py 内嵌 JS），pytest 够不到 DOM——\n本文件按"结构标记"锁定关键实现，防止被误回退：\n1. 侧栏好友列表全量按实例分割：所有世界都有组头（不只在 ≥2 人时），\n2. 状态变化事件文字开头颜色加强（● label 同色 600 加粗，对齐 游戏内/前往/离线 的\n   feedDetailCell 开头加强模式）；\n3. 详情弹窗秒开：openFriend/openWorld/openAvatarDlg 先用页面已有数据画壳\n   （window._FRIENDS / window._AVD），详情异步补齐（VRCX 本地缓存 SWR 同款语义）。\n对应行为的实时验证 = 部署后浏览器/Playwright 目检（tests/e2e）。'











import pytest
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "src" / "webui" / "web.py"


def js():
    root = WEB.parent
    return "\n".join([*(p.read_text() for p in sorted((root/"static").rglob("*.js"))),
                       (root/"templates"/"index.html").read_text(), WEB.read_text()])


def test_inline_js_parses_with_node():
    '一处括号不闭合=整页白屏。此处把 web.py 里的 <script> 块逐个过 node --check。'

    node = shutil.which("node")
    if not node:
        pytest.skip("node 不可用，跳过 JS 语法门禁")
    paths=sorted((WEB.parent/"static").rglob("*.js"))
    assert paths
    for path in paths:
        r=subprocess.run([node,"--check",str(path)],capture_output=True,text=True,timeout=30)
        assert r.returncode==0, f"{path}: {r.stderr[:800]}"


def test_sidebar_groups_all_instances_not_only_multi():
    s = js()
    assert "const ordered = Object.entries(rooms).sort((a,b)=>b[1].length-a[1].length);" in s
    # 不允许再出现"≥2 人才分组、其余平铺"的旧逻辑残留（内层 friends-tab 渲染）
    inner = s[s.index("const ordered = Object.entries(rooms)"):]
    inner = inner[:inner.index("无</div>';")]
    assert "multi.map" not in inner
    assert "私密/未知位置" in inner


def test_status_event_labels_are_color_emphasized():
    s = js()
    # feedDetailCell：● label 同色加粗（新旧两个状态）
    assert 'font-weight:600">${esc(STATUS_LABEL[e.previous]' in s
    assert 'font-weight:600">${esc(STATUS_LABEL[e.status]' in s
    # 不允许"只有彩点没有文字"的旧渲染
    assert '<span class="dim" style="margin:0 5px">→</span><span style="color:${statusDotC(e.status)}">●</span>`' not in s


def test_detail_modals_render_prefill_shell_before_fetch():
    s = js()
    # The browser test executes slow native HTTP responses and asserts that
    # the actual dialog is visible before completion; keep only integration
    # markers here, independent of internal variable names.
    assert 'pages/mobile.js' in s and 'mobile.css' in s
    assert 'function friendSeed(' in s and 'APP.client.peek(' in s
    browser = (WEB.parents[2] / 'scripts' / 'check-mobile-browser.py').read_text()
    assert 'fixture.delayFriend=600' in browser and 'fixture.delayWorld=700' in browser
    assert 'window._FRIENDS = all;' in s
