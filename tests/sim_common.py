"""F-04 仿真公共骨架：驱动 legacy watch() 真实代码路径（VRCX_PI_HOME 定位）。

被 tests/contract/test_f04_state_model.py 使用；
legacy/vrc-watch 的两个脚本测试保留独立副本（冻结）。
"""
import json
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_HOME = (os.environ.get("VRCX_PI_SRC")
         or os.environ.get("VRCX_PI_HOME")
         or str(_REPO / "src" / "webui"))   # 默认=现役实现；legacy 仅显式指定时测
sys.path.insert(0, _HOME)

import vrc_watch  # noqa: E402  (legacy 实现，冻结迁移来源)


def fresh_env(tmp_path, watch_list=()):
    """隔离环境：临时 config/auth/db，WS 线程置空（本骨架只覆盖轮询状态机）"""
    d = Path(tmp_path)
    vrc_watch.DIR = str(d)
    vrc_watch.CONFIG_PATH = str(d / "config.json")
    vrc_watch.DB_PATH = str(d / "vrc_watch.db")
    vrc_watch.AUTH_PATH = str(d / "auth.json")
    open(vrc_watch.AUTH_PATH, "w").write("{}")
    write_cfg(watch_list)
    vrc_watch.ws_pipeline_thread = lambda *a, **k: None


def write_cfg(watch_list=(), **over):
    cfg = {"poll_seconds": 15, "watch_list": list(watch_list),
           "watch_favorites": False, "notify_online": True, "notify_offline": True,
           "notify_world_change": True, "notify_active": True, "notify_status": False,
           "notify_desc": False, "notify_avatar": True,
           "bark": {"enabled": False}, "telegram": {"enabled": False}}
    cfg.update(over)
    with open(vrc_watch.CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f)


def fr(uid, name, location="wrld_x:1~hidden", state=None, status="active",
       desc="", platform="standalonewindows", avatar=None, tags=()):
    return {"id": uid, "displayName": name,
            "location": location,
            "state": state or ("online" if location.startswith("wrld_") else "active"),
            "status": status, "statusDescription": desc,
            "last_platform": platform, "currentAvatarImageUrl": avatar or "",
            "tags": list(tags)}


def run(rounds, watch_list=()):
    '驱动 watch() 走完各轮，返回 (pushes, db)。\n    rounds: 每轮 (收藏夹, 在线好友列表)\n    替换的模块属性在结束时恢复'


    _saved = {k: getattr(vrc_watch, k) for k in
              ("push", "time", "now_ts", "threading", "_wait_wake_or_refresh", "VRChatClient")}
    pushes = []
    state = {"round": 0}

    class FakeClient:
        def __init__(self, cfg):
            pass

        def get_friends(self, offline=False):
            if offline:
                return []
            if state["round"] >= len(rounds):
                raise StopIteration
            favs, online = rounds[state["round"]]
            state["round"] += 1
            if state["round"] == 1 and favs:
                write_cfg(list(favs))  # 首轮后应用收藏夹
            return online

        def get_favorite_friend_ids(self):
            return FAVS[min(state["round"], len(FAVS)) - 1]

        def get_world_name(self, wid, db, cache_only=False):
            return {"wrld_x": "世界X", "wrld_priv": None}.get(wid, f"世界{wid[:6]}")

    vrc_watch.now_ts = lambda: 1800000000 + state['round'] * 30
    vrc_watch.VRChatClient = FakeClient
    vrc_watch.push = lambda cfg, title, body: pushes.append(title) or pushes.append(body)
    vrc_watch.time.sleep = lambda s: None
    # 等待即时化：轮询等待（_wait_wake_or_refresh）与对账等待（wake.wait(poll)）都立即返回
    vrc_watch._wait_wake_or_refresh = lambda wake, poll, last: -1
    class _InstantEvent:
        def set(self): pass
        def clear(self): pass
        def is_set(self): return False
        def wait(self, timeout=None): return True
    class _FakeThread:
        def __init__(self, target=None, args=(), daemon=None, **kw):
            self._target, self._args = target, args
        def start(self):
            if self._target: self._target(*self._args)
    vrc_watch.threading = type("InstantThreading", (), {
        "Event": staticmethod(lambda: _InstantEvent()),
        "Thread": _FakeThread})

    write_cfg(watch_list)
    db = vrc_watch.init_db()
    try:
        vrc_watch.watch(load_cfg(), db)
    except StopIteration:
        pass
    finally:
        for k, v in _saved.items():
            setattr(vrc_watch, k, v)
    return pushes, db


def load_cfg():
    return vrc_watch.load_config()
