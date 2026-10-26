"""F-09 收藏与分组 · 写操作契约测试（对照 vendor/VRCX src/api/favorite.js @174551e）

上游端点：
- POST   favorites                        {type, favoriteId, tags:[组名]}   加入收藏
- DELETE favorites/{objectId}             （objectId=fav_xxx 收藏记录 id）   移出收藏
- PUT    favorite/group/{type}/{group}/{myUid}  {displayName, visibility}   建/重命名组
- DELETE favorite/group/{type}/{group}/{myUid}                              清空/删组
- GET    auth/user/favoritelimits                                            容量限制
本文件在 backend/favorites.py 实现前必须 FAIL。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import pytest

from favorites import FavoriteService
from errors import AuthCode


class FakeTransport:
    def __init__(self, script=None):
        self.script = script or {}
        self.calls = []
        self.cookies = {}

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
        st, j = self.script.get(("PUT", path), (200, {}))
        return st, j

    def delete(self, path, headers=None):
        self.calls.append(("DELETE", path, None))
        st, j = self.script.get(("DELETE", path), (200, {}))
        return st, j


MY = "usr_me"


def svc(script=None):
    t = FakeTransport(script)
    # 注入当前用户 id（上游 getCurrentUserId()）
    t.get = _wrap_get(t)
    s = FavoriteService(transport=t, current_user_id=MY)
    return s, t


def _wrap_get(t):
    orig = t.get
    def g(path, headers=None):
        return orig(path, headers)
    return g


def test_add_favorite_posts_upstream_shape():
    s, t = svc({("POST", "favorites"): (200, {"id": "fav_1"})})
    r = s.add("friend", "usr_a", group="group_0")
    assert r.ok
    method, path, payload = [c for c in t.calls if c[0] == "POST"][0]
    assert path == "favorites"
    assert payload["type"] == "friend" and payload["favoriteId"] == "usr_a"
    assert payload["tags"] == ["group_0"]          # 上游：组名放 tags[0]


def test_remove_favorite_uses_fav_object_id():
    s, t = svc({("DELETE", "favorites/fav_9"): (200, {})})
    r = s.remove("fav_9")
    assert r.ok
    assert ("DELETE", "favorites/fav_9", None) in t.calls


def test_rename_group_uses_put_with_displayname():
    s, t = svc()
    r = s.save_group("friend", "group_0", display_name="新名字", visibility="private")
    assert r.ok
    put = [c for c in t.calls if c[0] == "PUT"][0]
    assert put[1] == f"favorite/group/friend/group_0/{MY}"
    assert put[2]["displayName"] == "新名字"
    assert put[2]["visibility"] == "private"


def test_clear_group_uses_delete():
    s, t = svc()
    r = s.clear_group("world", "worlds1")
    assert r.ok
    assert ("DELETE", f"favorite/group/world/worlds1/{MY}", None) in t.calls


def test_limits_endpoint():
    s, t = svc({("GET", "auth/user/favoritelimits"): (
        200, {"maxFavoriteFriends": 150, "maxFavoriteWorlds": 100})})
    r = s.limits()
    assert r["maxFavoriteFriends"] == 150


def test_error_passthrough_not_swallowed():
    # 429 必须以 RATE_LIMITED 冒泡，不得吞成空成功（主提示词 §五）
    s, t = svc({("POST", "favorites"): (429, {"error": {"message": "Too Many Requests",
                                                        "status_code": 429}})})
    r = s.add("friend", "usr_a")
    assert not r.ok and r.code == AuthCode.RATE_LIMITED
