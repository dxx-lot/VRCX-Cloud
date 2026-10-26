"""F-02 统一认证错误模型。

对照上游 VRCX @174551e：
- src/stores/auth.js:280,516  'Invalid Username/Email or Password' 为独立错误
- src/stores/auth.js:276      网络失败与凭据失败严格区分（network issue fingerprint）
- 主提示词 §五                 登录失败/服务异常/网络错误/限流/会话过期必须是不同状态
"""


class AuthCode:
    OK = "OK"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"          # 用户名/密码错误（含上游原话）
    INVALID_2FA_CODE = "INVALID_2FA_CODE"                # 2FA 验证码错误
    EMAIL_OTP_REQUIRED = "EMAIL_OTP_REQUIRED"            # 邮箱验证码已发送
    TOTP_REQUIRED = "TOTP_REQUIRED"                      # 需要 TOTP（可回退恢复码）
    RECOVERY_CODE_REQUIRED = "RECOVERY_CODE_REQUIRED"    # 需要恢复码
    NETWORK_ERROR = "NETWORK_ERROR"                      # 连接失败/DNS/超时
    RATE_LIMITED = "RATE_LIMITED"                        # 429
    SERVER_ERROR = "SERVER_ERROR"                        # 5xx
    SESSION_EXPIRED = "SESSION_EXPIRED"                  # 会话 cookie 失效
    BAD_REQUEST = "BAD_REQUEST"                          # 400


class AuthResult:
    """登录/验证结果：code + 上游 JSON（不吞错；原始响应用于 UI 与日志审计脱敏后留存）"""

    def __init__(self, code, user=None, requires=None, raw=None):
        self.code = code
        self.user = user
        self.requires = requires or []
        self.raw = raw

    def is_network(self):
        return self.code == AuthCode.NETWORK_ERROR

    @property
    def ok(self):
        return self.code == AuthCode.OK

    def __repr__(self):  # 防止意外把 raw 打进日志
        return f"AuthResult(code={self.code})"
