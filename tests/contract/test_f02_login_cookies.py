'F-02 登录 cookie 卫生 · 契约测试（对照上游 VRCX @174551e）\n\n上游依据（vendor/VRCX）：\n- src/stores/auth.js:540  login() 首步 await webApiService.clearCookies()\n  —— 每次密码挑战都必须从干净 cookie 罐发起\n- src/stores/auth.js:225  resendEmail2fa() 重发验证码 = clearCookies + 完整重新登录\n- src/webui/web.py:3238   登录链 Basic → emailOtp verify 依赖 cookie 连续性\n  —— 验证步必须保留挑战会话 cookie，绝不能误清\n\n背景：旧实现把 auth-ui.json 遗留的 twoFactorAuth cookie 带上\n发起挑战，VRChat 视同该会话验证码已发过、静默不再发邮件——用户官网能收到\n（干净浏览器），DIY UI 永远收不到。修复 = 首步清空 cookie 罐。\n\n测试替身（铁律 8：形状与生产 transport 一致）：\n- 生产层（src/webui/vrc_watch.py）：真实 requests.Session + 本地脚本化 HTTP 服务，\n  cookie 罐/请求头/Set-Cookie 全部走真实 transport 语义；\n- 契约镜像层（backend/login_client.py）：最小可编程 transport\n  （FakeTransport 的形状见 test_f02_login.py）。'


















import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "backend"))
sys.path.insert(0, str(_REPO / "src" / "webui"))

import pytest

import vrc_watch
from login_client import LoginClient


# ---------- 契约镜像层（backend/login_client.py） ----------

class _MirrorTransport:
    """最小等价替身：形状同 test_f02_login.FakeTransport（记录调用 + 可编程响应）。"""

    def __init__(self):
        self.cookies = {}
        self.calls = []

    def get(self, path, headers=None):
        self.calls.append(("GET", path, dict(headers or {})))
        return 401, {"requiresTwoFactorAuth": ["emailOtp"], "verified": False}

    def post(self, path, json=None, headers=None):
        self.calls.append(("POST", path, dict(headers or {})))
        return 404, {}


def test_mirror_login_clears_stale_cookies_before_challenge():
    t = _MirrorTransport()
    t.cookies.update({"auth": "stale-auth", "twoFactorAuth": "stale-2fa"})
    c = LoginClient(transport=t)
    c.login("user", "pw")
    assert t.cookies == {}  # 挑战请求发出前必须清空（上游 auth.js:540）


# ---------- 生产层（src/webui/vrc_watch.py + 真实 requests transport） ----------

class _ScriptedAPI:
    """按脚本顺序回放响应，记录每个到达请求的 Cookie 头。"""

    def __init__(self):
        self.steps = []      # (status, json_body, set_cookie)
        self.seen = []       # (method, path, cookie_header)

    def add(self, status, body, set_cookie=None):
        self.steps.append((status, body, set_cookie))

    def handle(self, method, path, cookie):
        self.seen.append((method, path, cookie or ""))
        assert self.steps, "脚本耗尽：收到未预期的请求 " + method + " " + path
        return self.steps.pop(0)


@pytest.fixture()
def vrchat_api(monkeypatch):
    """vrc_watch.BASE 指向本地脚本化 HTTP 服务：真实 HTTP 往返 + 真实 cookie 罐。"""
    api = _ScriptedAPI()

    class Handler(BaseHTTPRequestHandler):
        def _reply(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
            status, body, set_cookie = api.handle(
                self.command, self.path, self.headers.get("Cookie") or "")
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            if set_cookie:
                self.send_header("Set-Cookie", set_cookie)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = do_POST = _reply

        def log_message(self, *a):  # 静音测试输出
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(vrc_watch, "BASE",
                        f"http://127.0.0.1:{server.server_address[1]}/api/1")
    yield api
    server.shutdown()
    server.server_close()


def prod_client(monkeypatch, tmp_path):
    """生产构造链：VRChatClient 从 auth-ui.json（D-P1-S4 规范存储）加载遗留 cookie。"""
    monkeypatch.setattr(vrc_watch, "AUTH_PATH", str(tmp_path / "auth-ui.json"))
    with open(tmp_path / "auth-ui.json", "w", encoding="utf-8") as f:
        json.dump({"cookies": {"auth": "stale-auth", "twoFactorAuth": "stale-2fa"}}, f)
    return vrc_watch.VRChatClient({"user_agent": "contract-test/1.0"})


def test_challenge_starts_with_clean_cookie_jar(vrchat_api, monkeypatch, tmp_path):
    c = prod_client(monkeypatch, tmp_path)
    # 前置：__init__ 确实从 auth-ui.json 装入了遗留 cookie（复现生产现场）
    assert {ck.name for ck in c.s.cookies} >= {"auth", "twoFactorAuth"}
    vrchat_api.add(401, {"requiresTwoFactorAuth": ["emailOtp"], "verified": False},
                   set_cookie="token=challenge-1; Path=/")
    with pytest.raises(vrc_watch.TwoFactorRequired) as ei:
        c.login("user", "pw")
    assert "emailOtp" in ei.value.kinds
    method, path, cookie = vrchat_api.seen[0]
    assert method == "GET" and path.endswith("/auth/user")
    assert cookie == ""  # 关键断言：挑战请求不带任何遗留 cookie


def test_verify_step_keeps_challenge_session_cookies(vrchat_api, monkeypatch, tmp_path):
    c = prod_client(monkeypatch, tmp_path)
    vrchat_api.add(401, {"requiresTwoFactorAuth": ["emailOtp"], "verified": False},
                   set_cookie="token=challenge-1; Path=/")
    vrchat_api.add(200, {"verified": True})
    vrchat_api.add(200, {"id": "usr_x", "displayName": "tester"})
    with pytest.raises(vrc_watch.TwoFactorRequired):
        c.login("user", "pw")
    c.login("user", "pw", totp_code="654321", kinds=["emailOtp"])
    _, path, cookie = vrchat_api.seen[1]
    assert path.endswith("/auth/twofactorauth/emailotp/verify")
    # 连续性（web.py:3238）：验证步必须带上挑战会话 cookie，不能误清
    assert "token=challenge-1" in cookie


def test_resend_challenge_clears_previous_challenge_cookies(vrchat_api, monkeypatch, tmp_path):
    c = prod_client(monkeypatch, tmp_path)
    vrchat_api.add(401, {"requiresTwoFactorAuth": ["emailOtp"], "verified": False},
                   set_cookie="token=challenge-1; Path=/")
    with pytest.raises(vrc_watch.TwoFactorRequired):
        c.login("user", "pw")
    # 用户重交账号密码 = 上游 resendEmail2fa 语义：新挑战必须又是干净罐
    vrchat_api.add(401, {"requiresTwoFactorAuth": ["emailOtp"], "verified": False},
                   set_cookie="token=challenge-2; Path=/")
    with pytest.raises(vrc_watch.TwoFactorRequired):
        c.login("user", "pw")
    _, path, cookie = vrchat_api.seen[1]
    assert path.endswith("/auth/user")
    assert cookie == "" and "token=challenge-1" not in cookie
