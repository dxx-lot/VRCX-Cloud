'轮询抖动 + 自身在场权威合并 · 契约测试\n\n- _poll_delay：±15% 抖动（反机器人启发式抓秒表级规律），越界即错；\n- get_self：/auth/user 的 state/location 是"自己看自己"的陈旧视图（在线也报 offline），'





import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src" / "webui"))

import web
import vrc_watch


# ---------- 轮询抖动 ----------

def test_poll_delay_stays_within_jitter_band():
    for _ in range(300):
        d = vrc_watch._poll_delay(30)
        assert 30 * 0.85 <= d <= 30 * 1.15, d


def test_poll_delay_never_below_one_second():
    assert vrc_watch._poll_delay(1) >= 1.0


# ---------- get_self 在场合并 ----------

class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._p = payload

    def json(self):
        return self._p


class _FakeSession:
    """按 path 回放：auth/user 报陈旧 offline，users/{id} 报权威 online"""

    def __init__(self):
        self.calls = []

    def get(self, path, timeout=None):
        self.calls.append(path)
        if path.endswith("/auth/user"):
            return _Resp(200, {"id": "usr_me", "displayName": "测试",
                               "state": "offline", "location": ""})
        if "/users/usr_me" in path:
            return _Resp(200, {"id": "usr_me", "displayName": "测试",
                               "state": "online",
                               "location": "wrld_x:1",
                               "currentAvatarThumbnailImageUrl": "https://cdn/t.png",
                               "last_login": "2026-10-06T10:00:00Z"})
        return _Resp(404, {})


class _FakeClient:
    def __init__(self):
        self.s = _FakeSession()


def test_get_self_merges_authoritative_presence():
    web._self_cache.update({"ts": 0, "data": None})
    c = _FakeClient()
    s = web.get_self(c, force=True)
    assert s["state"] == "online", "在游戏里却显示 offline = 合并失败"
    assert s["location"] == "wrld_x:1"
    assert s["thumb"] == "https://cdn/t.png"
    assert len(c.s.calls) == 2  # auth/user（会话确认）+ users/{id}（权威在场）


def test_get_self_auth_fail_returns_none():
    class _Dead:
        class s:
            @staticmethod
            def get(path, timeout=None):
                return _Resp(401, {})

    web._self_cache.update({"ts": 0, "data": None})
    assert web.get_self(_Dead(), force=True) is None


def test_get_self_uses_cache_within_ttl():
    c = _FakeClient()
    web._self_cache.update({"ts": 0, "data": None})
    web.get_self(c, force=True)
    n_calls = len(c.s.calls)
    web.get_self(c)  # 缓存内：不再发请求
    assert len(c.s.calls) == n_calls
