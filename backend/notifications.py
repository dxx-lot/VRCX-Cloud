"""F-12 通知交互服务——上游 notification.js @174551e 的端点等价适配。

- PUT auth/user/notifications/{id}/accept  接受好友请求
- PUT auth/user/notifications/{id}/hide    隐藏（界面上的删除）
- PUT auth/user/notifications/{id}/see     标记已读
- DELETE notifications/{id}                删除通知
- POST invite/{uid} / requestInvite/{uid}  邀请 / 请求邀请
- POST invite/{inviteId}/response          回应邀请
"""
import requests

from errors import AuthCode, AuthResult


class NotificationService:
    def __init__(self, transport):
        self.t = transport

    @staticmethod
    def _result(status, j):
        if status in (200, 201):
            return AuthResult(AuthCode.OK, raw=j)
        code = AuthCode.RATE_LIMITED if status == 429 else (
            AuthCode.SERVER_ERROR if status >= 500 else AuthCode.BAD_REQUEST)
        return AuthResult(code, raw=j)

    def list(self, ftype=None):
        try:
            params = {"type": ftype} if ftype else None
            st, j = self.t.get("auth/user/notifications", params)
            return {"items": j if st == 200 and isinstance(j, list) else [],
                    "error": None if st == 200 else f"HTTP {st}"}
        except requests.RequestException as e:
            return {"items": [], "error": f"网络错误: {e}"}

    def _put(self, path):
        try:
            st, j = self.t.put(path)
        except requests.RequestException as e:
            return AuthResult(AuthCode.NETWORK_ERROR, raw=str(e))
        return self._result(st, j)

    def accept_friend_request(self, notification_id):
        return self._put(f"auth/user/notifications/{notification_id}/accept")

    def hide(self, notification_id):
        return self._put(f"auth/user/notifications/{notification_id}/hide")

    def see(self, notification_id):
        return self._put(f"auth/user/notifications/{notification_id}/see")

    def delete(self, notification_id):
        try:
            st, j = self.t.delete(f"notifications/{notification_id}")
        except requests.RequestException as e:
            return AuthResult(AuthCode.NETWORK_ERROR, raw=str(e))
        return self._result(st, j)

    def invite(self, receiver_uid, message=None):
        payload = {"message": message} if message else None
        try:
            st, j = self.t.post(f"invite/{receiver_uid}", json=payload)
        except requests.RequestException as e:
            return AuthResult(AuthCode.NETWORK_ERROR, raw=str(e))
        return self._result(st, j)

    def request_invite(self, receiver_uid, message=None):
        payload = {"message": message} if message else None
        try:
            st, j = self.t.post(f"requestInvite/{receiver_uid}", json=payload)
        except requests.RequestException as e:
            return AuthResult(AuthCode.NETWORK_ERROR, raw=str(e))
        return self._result(st, j)

    def invite_response(self, invite_id, response):
        try:
            st, j = self.t.post(f"invite/{invite_id}/response", {"response": response})
        except requests.RequestException as e:
            return AuthResult(AuthCode.NETWORK_ERROR, raw=str(e))
        return self._result(st, j)
