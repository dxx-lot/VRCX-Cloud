"""F-02 登录客户端——上游契约（VRCX @174551e）的 Pi 后端适配器。

上游依据（vendor/VRCX）：
- src/stores/auth.js:748   Basic 头 = btoa(encodeURIComponent(u) + ':' + encodeURIComponent(p))
- src/stores/auth.js:780   requiresTwoFactorAuth 含 'emailOtp' → 邮箱流程；否则 TOTP（可回退恢复码）
- src/api/auth.js          verify 端点: auth/twofactorauth/{totp|otp|emailotp}/verify
- src/stores/auth.js:280   'Invalid Username/Email or Password' → INVALID_CREDENTIALS
- src/stores/auth.js:208   登出 = 清除本地会话 cookie（clearCookiesTryLogin 语义）

传输层可注入（FakeTransport），本模块不含网络代码；网络访问由真实 transport 提供。
"""
import base64
from urllib.parse import quote

from errors import AuthCode, AuthResult


def upstream_basic_header(user, password):
    """与上游 auth.js:748 逐字节一致：
    btoa(encodeURIComponent(username) + ':' + encodeURIComponent(password))"""
    def enc(s):
        out = []
        for ch in str(s):
            if ch.isalnum() or ch in "-_.!~*'":
                out.append(ch)
            else:
                out.extend(f"%{b:02X}" for b in ch.encode("utf-8"))
        return "".join(out)
    raw = f"{enc(user)}:{enc(password)}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


class LoginClient:
    BASE = "auth"  # 相对路径（真实 transport 负责拼 https://api.vrchat.cloud/api/1/）

    def __init__(self, transport):
        self.t = transport
        self._logged_in = False

    # ---------- 内部 ----------
    def _get(self, path, headers=None):
        return self.t.get(path, headers=headers)

    def _post(self, path, payload, headers=None):
        return self.t.post(path, json=payload, headers=headers)

    @staticmethod
    def _classify(status, j):
        """状态码+响应体 → AuthCode（对照上游错误处理）"""
        msg = ""
        if isinstance(j, dict):
            err = j.get("error")
            if isinstance(err, dict):
                msg = err.get("message") or ""
            elif isinstance(j.get("message"), str):
                msg = j["message"]
        if status == 401:
            if j.get("requiresTwoFactorAuth"):
                kinds = j["requiresTwoFactorAuth"]
                if "emailOtp" in kinds:
                    return AuthCode.EMAIL_OTP_REQUIRED
                if "totp" in kinds:
                    return AuthCode.TOTP_REQUIRED
                if "otp" in kinds:
                    return AuthCode.RECOVERY_CODE_REQUIRED
            if "Invalid Username/Email or Password" in msg or "Invalid Code" in msg:
                return AuthCode.INVALID_CREDENTIALS
            if "Invalid Code" in msg:
                return AuthCode.INVALID_2FA_CODE
            return AuthCode.SESSION_EXPIRED
        if status == 429:
            return AuthCode.RATE_LIMITED
        if status >= 500:
            return AuthCode.SERVER_ERROR
        if status == 400:
            return AuthCode.BAD_REQUEST
        return AuthCode.SESSION_EXPIRED if status == 401 else AuthCode.SERVER_ERROR

    # ---------- 登录 ----------
    def login(self, username, password):
        """Basic 认证 GET auth/user（上游主登录路径，auth.js:748/780）"""
        # 上游 login() 首步 clearCookies（auth.js:540）：挑战必须从干净 cookie 罐发起，
        # 否则 VRChat 视同该会话验证码已发过、静默不再发邮件（与 src/webui/vrc_watch.py 同契约）。
        self.t.cookies.clear()
        headers = {"Authorization": upstream_basic_header(username, password)}
        try:
            status, j = self._get("auth/user", headers=headers)
        except (ConnectionError, TimeoutError, OSError):
            return AuthResult(AuthCode.NETWORK_ERROR)
        if status == 200 and isinstance(j, dict) and j.get("id"):
            self._logged_in = True
            return AuthResult(AuthCode.OK, user=j, raw=j)
        code = self._classify(status, j if isinstance(j, dict) else {})
        requires = (j or {}).get("requiresTwoFactorAuth") or [] if isinstance(j, dict) else []
        return AuthResult(code, requires=requires, raw=j)

    # ---------- 2FA ----------
    def _verify(self, path, code):
        try:
            status, j = self._post(path, {"code": code})
        except (ConnectionError, TimeoutError, OSError):
            return AuthResult(AuthCode.NETWORK_ERROR)
        if status == 200 and isinstance(j, dict) and j.get("verified"):
            self._logged_in = True
            return AuthResult(AuthCode.OK, raw=j)
        if status == 401:
            msg = (j.get("error") or {}).get("message", "") if isinstance(j, dict) else ""
            if "Invalid Code" in msg or "Invalid" in msg:
                return AuthResult(AuthCode.INVALID_2FA_CODE)
            return AuthResult(AuthCode.SESSION_EXPIRED)
        return AuthResult(self._classify(status, j if isinstance(j, dict) else {}))

    def verify_totp(self, code):
        return self._verify("auth/twofactorauth/totp/verify", code)

    def verify_email_otp(self, code):
        return self._verify("auth/twofactorauth/emailotp/verify", code)

    def verify_recovery(self, code):
        return self._verify("auth/twofactorauth/otp/verify", code)

    # ---------- 会话 ----------
    def session(self):
        """GET auth/user（无 Basic）：200=OK，401=SESSION_EXPIRED"""
        try:
            status, _ = self._get("auth/user")
        except (ConnectionError, TimeoutError, OSError):
            return AuthCode.NETWORK_ERROR
        return AuthCode.OK if status == 200 else AuthCode.SESSION_EXPIRED

    def cookies(self):
        return dict(self.t.cookies)

    def logout(self):
        """上游 clearCookies 语义（src/stores/auth.js:208）：清除本地会话"""
        self.t.cookies.clear()
        self._logged_in = False
