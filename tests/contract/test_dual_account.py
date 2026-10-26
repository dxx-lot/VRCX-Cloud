'双账号同页（相互隔离）· 契约测试\n\n- 对端数据走服务端转发 /api/peer-self（浏览器零跨域），对端卡只读；\n- 切换 = 纯 DOM 显隐（两卡常驻），零请求 → 天然秒切；\n- peer_url 来自 config（A→8001，B→8000，双向可看）。'





import sys
import json
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src" / "webui"))

import pytest

import web
from services.routes import ApiRouter

def web_sources():
    root=_REPO / "src" / "webui"
    return "\n".join([*(p.read_text() for p in sorted((root/"static").rglob("*.js"))),
                       (root/"templates"/"index.html").read_text(), (root/"web.py").read_text()])


def test_peer_self_endpoint_wired():
    s = web_sources()
    assert "def api_peer_self():" in s
    assert "/api/peer-self" in web.ApiRouter({}).allowed("GET")
    # 对端已做全：可登出（中继），只读标记废除
    assert "onclick=\"doPeerLogout()\"" in s
    assert "对端只读" not in s


def test_peer_login_logout_relay_wired():
    s = web_sources()
    assert "def _peer_post(" in s and "def api_peer_login(body):" in s and "def api_peer_logout():" in s
    assert "/api/peer-login" in web.ApiRouter({}).allowed("POST")
    assert "/api/peer-logout" in web.ApiRouter({}).allowed("POST")
    assert "async function doPeerLogin()" in s and "async function doPeerLogout()" in s
    # 对端表单用独立 ID 集（p_*），与本机表单互不串扰
    assert 'id="p_username"' in s and 'id="p_password"' in s and 'id="p_code"' in s
    assert "switchAcct" in s and "acctPeerForm" in s


def test_switch_is_pure_dom_toggle():
    """秒切的本质：切换只做显隐与样式，不发任何请求。"""
    s = web_sources()
    body = s[s.index("function switchAcct"):s.index("const OV_EV")]
    assert "api(" not in body and "fetch(" not in body
    assert 'getElementById(\'acctSelf\').classList.toggle' in body
    assert 'getElementById(\'acctPeer\').classList.toggle' in body


def test_peer_self_unconfigured(monkeypatch):
    monkeypatch.setattr(web, "load_config", lambda: {})
    assert web.api_peer_self() == {"peer_configured": False}


def test_peer_self_success(monkeypatch):
    monkeypatch.setattr(web, "load_config", lambda: {"peer_url": "http://127.0.0.1:8001"})

    response = web.requests.Response()
    response.status_code = 200
    response._content = json.dumps({"logged_in": True, "name": "B号"}).encode()
    response._content_consumed = True
    monkeypatch.setattr(web.requests, "get", lambda url, **kwargs: response)
    out = web.api_peer_self()
    assert out["peer_configured"] is True
    assert out["peer"]["name"] == "B号"


def test_peer_self_unreachable(monkeypatch):
    monkeypatch.setattr(web, "load_config", lambda: {"peer_url": "http://127.0.0.1:8001"})

    def _boom(url, **kwargs):
        raise web.requests.RequestException("connection refused")

    monkeypatch.setattr(web.requests, "get", _boom)
    out = web.api_peer_self()
    assert out["peer_configured"] is True and "peer_error" in out
