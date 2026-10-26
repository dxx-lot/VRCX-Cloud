"""F-14 群组管理动作 · 契约测试（对照 vendor/VRCX src/api/group.js @174551e）

上游端点：
- GET  groups/{groupId}/members              成员列表（已交付）
- GET  groups/{groupId}/posts/{postId}       群组帖子
- GET  groups/{groupId}                      详情（已交付）
- DELETE groups/{groupId}/members/{userId}   退出群组（LeaveGroup）
- PUT  groups/{groupId}/members/{userId}     成员行为（含 representation 等）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from group_client import leave_group, get_group_posts


class FakeResponse:
    def __init__(self, status, j):
        self.status_code = status
        self._j = j
    def json(self):
        return self._j


class FakeTransport:
    def __init__(self, script):
        self.script = script
    def get(self, path, headers=None, params=None, **kw):
        base = path.split("?")[0]
        for k, v in self.script.items():
            if base.endswith(k):
                return FakeResponse(v[0], v[1])
        return FakeResponse(404, {})
    def delete(self, path, headers=None, **kw):
        base = path.split("?")[0]
        for k, v in self.script.items():
            if base.endswith(k):
                return FakeResponse(v[0], v[1])
        return FakeResponse(404, {})


def test_leave_group_success():
    t = FakeTransport({"groups/grp_1/members/usr_me": (200, {})})
    r = leave_group(t, "grp_1", "usr_me")
    assert r.ok


def test_group_posts():
    t = FakeTransport({"groups/grp_1/posts": (200, [
        {"id": "post_1", "message": "公告一", "createdAt": "2026-09-01T00:00:00Z"},
        {"id": "post_2", "message": "公告二", "createdAt": "2026-09-15T00:00:00Z"}])})
    r = get_group_posts(t, "grp_1")
    assert r["ok_count"] == 2 and r["posts"][0]["message"] == "公告一"

