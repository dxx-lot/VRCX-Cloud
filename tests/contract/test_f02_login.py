"""F-02 登录与会话 · 契约测试（对照上游 VRCX @174551e）

上游依据（vendor/VRCX）：
- src/stores/auth.js:748  Basic 头 = btoa(encodeURIComponent(u) + ':' + encodeURIComponent(p))
- src/stores/auth.js:780  requiresTwoFactorAuth 含 'emailOtp' → 邮箱验证码流程；否则 TOTP/恢复码
- src/api/auth.js         三条验证端点: auth/twofactorauth/{totp|otp|emailotp}/verify
- src/stores/auth.js:280,516  'Invalid Username/Email or Password' 是独立错误状态
- src/stores/auth.js:276  网络失败与凭据失败区分（network issue fingerprint）
- src/stores/auth.js:208  clearCookies 语义（登出=清会话）

本文件在 backend/login_client.py 实现前必须 FAIL（红→绿流程）。
"""
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import pytest

from login_client import AuthCode, LoginClient


class FakeTransport:
    """可编程传输层：按 (method, path) 返回 (status, json, set_cookies)。
    无网络；响应形状取自上游真实响应（见 fixtures 注释）。"""

    def __init__(self, script=None, fail_connect=False):
        self.script = script or {}          # (method, path) -> (status, json, cookies)
        self.fail_connect = fail_connect    # True 模拟断网
        self.calls = []                     # (method, path, headers)
        self.cookies = {}

    def get(self, path, headers=None):
        self.calls.append(("GET", path, headers or {}))
        if self.fail_connect:
            raise ConnectionError("unreachable")
        st, j, ck = self.script.get(("GET", path.split("?")[0]), (404, {}, None))
        if ck:
            self.cookies.update(ck)
        return st, j

    def post(self, path, json=None, headers=None):
        self.calls.append(("POST", path, headers or {}))
        if self.fail_connect:
            raise ConnectionError("unreachable")
        st, j, ck = self.script.get(("POST", path), (404, {}, None))
        if ck:
            self.cookies.update(ck)
        return st, j


def upstream_basic_header(user, pw):
    """上游算法的独立实现（对照基准，不从被测代码 import）：
    src/stores/auth.js:748  btoa(encodeURIComponent(u)+':'+encodeURIComponent(p))"""
    def enc(s):
        # JavaScript encodeURIComponent 精确语义
        keep = "A-Za-z0-9-_.!~*'"
        out = ""
        for ch in s:
            if ch.isalnum() or ch in "-_.!~*'":
                out += ch
            else:
                out += "".join(f"%{b:02X}" for b in ch.encode("utf-8"))
        return out
    return "Basic " + base64.b64encode(f"{enc(user)}:{enc(pw)}".encode()).decode()


def make_client(script, fail_connect=False):
    t = FakeTransport(script, fail_connect)
    return LoginClient(transport=t), t


USER_OK = {"id": "usr_x", "displayName": "tester"}


def script_login(status, j):
    return {("GET", "auth/user"): (status, j, None)}


# ---------- 登录主流程 ----------

def test_login_success_sets_session_and_basic_header():
    c, t = make_client(script_login(200, USER_OK))
    res = c.login("user", "pw")
    assert res.code == AuthCode.OK and res.user["id"] == "usr_x"
    # 上游 748 行：Basic 头构造方式必须逐字节一致
    _, _, hdr = t.calls[0]
    assert hdr["Authorization"] == upstream_basic_header("user", "pw")


def test_basic_header_special_chars_match_upstream():
    c, t = make_client(script_login(200, USER_OK))
    c.login("user@test.com", "p@ss :wörd/100%")
    _, _, hdr = t.calls[0]
    assert hdr["Authorization"] == upstream_basic_header("user@test.com", "p@ss :wörd/100%")


def test_invalid_credentials_is_distinct_code():
    # 上游真实错误串（src/stores/auth.js:280）
    c, t = make_client(script_login(401, {"error": {"message": '"Invalid Username/Email or Password"',
                                                   "status_code": 401}}))
    res = c.login("u", "wrong")
    assert res.code == AuthCode.INVALID_CREDENTIALS
    assert not res.is_network()


def test_email_otp_required():
    c, _ = make_client(script_login(401, {"requiresTwoFactorAuth": ["emailOtp"], "verified": False}))
    res = c.login("u", "pw")
    assert res.code == AuthCode.EMAIL_OTP_REQUIRED


def test_totp_then_recovery_fallback():
    scr = script_login(401, {"requiresTwoFactorAuth": ["totp", "otp"], "verified": False})
    scr[("POST", "auth/twofactorauth/totp/verify")] = (200, {"verified": True}, None)
    c, t = make_client(scr)
    res = c.login("u", "pw")
    assert res.code == AuthCode.TOTP_REQUIRED
    ok = c.verify_totp("123456")
    assert ok.code == AuthCode.OK
    # 恢复码走 otp 端点（上游 auth.js verifyOTP）
    scr2 = script_login(401, {"requiresTwoFactorAuth": ["totp", "otp"], "verified": False})
    scr2[("POST", "auth/twofactorauth/otp/verify")] = (200, {"verified": True}, None)
    c2, t2 = make_client(scr2)
    c2.login("u", "pw")
    ok2 = c2.verify_recovery("recover-code")
    assert ok2.code == AuthCode.OK
    assert any(p.endswith("auth/twofactorauth/otp/verify") for _, p, _ in t2.calls)


def test_email_otp_verify_endpoint():
    scr = script_login(401, {"requiresTwoFactorAuth": ["emailOtp"], "verified": False})
    scr[("POST", "auth/twofactorauth/emailotp/verify")] = (200, {"verified": True}, None)
    c, t = make_client(scr)
    c.login("u", "pw")
    ok = c.verify_email_otp("654321")
    assert ok.code == AuthCode.OK
    assert ("POST", "auth/twofactorauth/emailotp/verify") in [(m, p) for m, p, _ in t.calls]


def test_wrong_2fa_code_is_distinct():
    scr = script_login(401, {"requiresTwoFactorAuth": ["emailOtp"], "verified": False})
    scr[("POST", "auth/twofactorauth/emailotp/verify")] = (
        401, {"error": {"message": "\"Invalid Code\"", "status_code": 401}}, None)
    c, _ = make_client(scr)
    c.login("u", "pw")
    ok = c.verify_email_otp("000000")
    assert ok.code == AuthCode.INVALID_2FA_CODE


# ---------- 错误状态区分（主提示词：网络/凭据/限流/服务器各不相同） ----------

def test_network_error_is_distinct_and_not_counted_as_credentials():
    c, _ = make_client({}, fail_connect=True)
    res = c.login("u", "pw")
    assert res.code == AuthCode.NETWORK_ERROR
    assert res.code != AuthCode.INVALID_CREDENTIALS


def test_rate_limited():
    c, _ = make_client(script_login(429, {"error": {"message": "Too Many Requests", "status_code": 429}}))
    assert c.login("u", "pw").code == AuthCode.RATE_LIMITED


def test_server_error():
    c, _ = make_client(script_login(503, {}))
    assert c.login("u", "pw").code == AuthCode.SERVER_ERROR


# ---------- 会话 ----------

def test_session_check_valid_and_expired():
    scr = script_login(200, USER_OK)
    scr[("GET", "auth/user")] = (200, USER_OK, None)  # 登录后校验有效
    c, _ = make_client(dict(scr))
    c.login("u", "pw")
    assert c.session() == AuthCode.OK
    # 会话过期 → 401
    scr2 = script_login(200, USER_OK)
    scr2[("GET", "auth/user")] = (401, {"error": {"message": '"Unauthorized"', "status_code": 401}}, None)
    c2, _ = make_client(scr2)
    c2.login("u", "pw")
    assert c2.session() == AuthCode.SESSION_EXPIRED


def test_logout_clears_cookies():
    scr = script_login(200, USER_OK)
    scr[("GET", "auth/user")] = (200, USER_OK, {"auth": "tok123", "twoFactorAuth": "tf1"})
    c, t = make_client(scr)
    c.login("u", "pw")
    assert c.cookies()
    c.logout()  # 上游 clearCookies 语义：清除本地会话
    assert not c.cookies()
