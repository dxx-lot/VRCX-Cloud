"""F-21 导入端 · 契约测试（上游 ImportDialog：建夹 400=已存在，继续加成员）"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from favgroup_import import import_favorite_groups


class FakeTransport:
    def __init__(self, script=None):
        self.script = script or {}
        self.calls = []
    def post(self, path, json=None, headers=None):
        self.calls.append(("POST", path, json))
        st, j = self.script.get(("POST", path), (200, {"ok": True}))
        return st, j


def test_import_creates_groups_and_favorites():
    t = FakeTransport()
    r = import_favorite_groups(t, {"type": "friend", "groups": [
        {"name": "group_0", "items": ["usr_1", "usr_2"]},
        {"name": "Group 2", "items": ["usr_3"]}]}, my_id="usr_me")
    posts = t.calls
    assert len(posts) == 5
    assert posts[0][1] == "auth/user/favgroups" and posts[0][2]["name"] == "group_0"
    favs = [p for p in posts if p[1] == "favorites"]
    by_id = {p[2]["favoriteId"]: p[2]["tags"] for p in favs}
    assert by_id["usr_1"] == ["group_0"] and by_id["usr_2"] == ["group_0"] \
        and by_id["usr_3"] == ["Group 2"]
    assert r["ok_count"] == 3


def test_group_already_exists_still_adds_members():
    t = FakeTransport()
    t.script[("POST", "auth/user/favgroups")] = (400, {"error": {"message": "exists"}})
    r = import_favorite_groups(t, {"type": "friend", "groups": [
        {"name": "已有组", "items": ["usr_1", "usr_2"]}]}, my_id="usr_me")
    favs = [p for p in t.calls if p[1] == "favorites"]
    assert r["ok_count"] == 2
    assert len(favs) == 2


def test_failure_does_not_abort_batch():
    # 建夹失败但收藏加入逐条 best-effort：不为单点失败中断整批（VRCX ImportDialog 语义）
    t = FakeTransport()
    t.calls = []
    def fail_post(path, json=None, headers=None):
        if path == "favorites":
            t.calls.append(("POST", path, json))
            return 200, {"id": "fav_x"}
        return 400, {"error": {"message": "boom", "status_code": 400}}
    t.post = fail_post
    r = import_favorite_groups(t, {"type": "friend", "groups": [
        {"name": "broken", "items": ["usr_1", "usr_2"]}]}, my_id="usr_me")
    assert r["ok_count"] == 2
    assert len([c for c in t.calls if c[1] == "favorites"]) == 2


def test_empty_payload():
    t = FakeTransport()
    r = import_favorite_groups(t, {"type": "friend", "groups": []}, my_id="usr_me")
    assert r["ok_count"] == 0 and r["fail_count"] == 0
