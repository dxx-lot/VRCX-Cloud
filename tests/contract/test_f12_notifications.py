"""F-12 通知交互 · 契约测试（对照 vendor/VRCX src/api/notification.js @174551e）

上游端点：
- GET  auth/user/notifications                       列表（含 type=friendRequest 过滤）
- PUT  auth/user/notifications/{id}/accept           接受好友请求
- PUT  auth/user/notifications/{id}/hide             隐藏/删除
- PUT  auth/user/notifications/{id}/see              标记已读
- DELETE notifications/{id}                          删除通知
- POST invite/{receiverUserId}                       发送邀请
- POST invite/{inviteId}/response {response,...}     回应邀请
本文件在 backend/notifications.py 实现前必须 FAIL。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import pytest

from notifications import NotificationService
from errors import AuthCode


class FakeTransport:
    def __init__(self, script=None):
        self.script = script or {}
        self.calls = []

    def get(self, path, headers=None):
        self.calls.append(("GET", path, None))
        st, j = self.script.get(("GET", path.split("?")[0]), (404, {}))
        return st, j

    def post(self, path, json=None, headers=None):
        self.calls.append(("POST", path, json))
        st, j = self.script.get(("POST", path), (200, {"ok": True}))
        return st, j

    def put(self, path, json=None, headers=None):
        self.calls.append(("PUT", path, json))
        st, j = self.script.get(("PUT", path), (200, {"success": True}))
        return st, j

    def delete(self, path, headers=None):
        self.calls.append(("DELETE", path, None))
        st, j = self.script.get(("DELETE", path), (200, {}))
        return st, j


def svc(script=None):
    t = FakeTransport(script)
    return NotificationService(transport=t), t


def test_list_notifications():
    fixture = [{"id": "notf_1", "type": "friendRequest",
                "senderUsername": " requester", "message": "hi"}]
    s, _ = svc({("GET", "auth/user/notifications"): (200, fixture)})
    r = s.list()
    assert r["items"][0]["id"] == "notf_1"


def test_accept_friend_request_uses_put_accept():
    s, t = svc()
    r = s.accept_friend_request("notf_9")
    assert r.ok
    assert ("PUT", "auth/user/notifications/notf_9/accept", None) in t.calls


def test_hide_and_see():
    s, t = svc()
    s.hide("notf_1")
    s.see("notf_2")
    assert ("PUT", "auth/user/notifications/notf_1/hide", None) in t.calls
    assert ("PUT", "auth/user/notifications/notf_2/see", None) in t.calls


def test_delete_notification():
    s, t = svc()
    s.delete("notf_3")
    assert ("DELETE", "notifications/notf_3", None) in t.calls


def test_send_invite_and_request_invite():
    s, t = svc({("POST", "invite/usr_a"): (200, {})})
    r = s.invite("usr_a")
    assert r.ok
    assert ("POST", "invite/usr_a") in [(c[0], c[1]) for c in t.calls]
    s2, t2 = svc({("POST", "requestInvite/usr_b"): (200, {})})
    s2.request_invite("usr_b")
    assert ("POST", "requestInvite/usr_b") in [(c[0], c[1]) for c in t2.calls]


def test_invite_response():
    s, t = svc()
    r = s.invite_response("invite_1", response="accept")
    assert r.ok
    post = [c for c in t.calls if c[0] == "POST"][0]
    assert post[1] == "invite/invite_1/response"
    assert post[2]["response"] == "accept"


def test_error_passthrough():
    s, t = svc({("PUT", "auth/user/notifications/notf_x/accept"): (
        429, {"error": {"message": "Too Many Requests", "status_code": 429}})})
    r = s.accept_friend_request("notf_x")
    assert not r.ok and r.code == AuthCode.RATE_LIMITED
