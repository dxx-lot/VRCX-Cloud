#!/usr/bin/env python3
# 仿真测试：验证关注名单自动跟随 VRChat 收藏夹（加收藏播报/取消收藏停止）
import json
import os
import sys
import tempfile

import os
sys.path.insert(0, os.environ.get("VRCX_PI_HOME",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "legacy", "vrc-watch")))
import vrc_watch

TMP = tempfile.mkdtemp()
vrc_watch.DIR = TMP
vrc_watch.CONFIG_PATH = os.path.join(TMP, "config.json")
vrc_watch.DB_PATH = os.path.join(TMP, "vrc_watch.db")
vrc_watch.AUTH_PATH = os.path.join(TMP, "auth.json")
open(vrc_watch.AUTH_PATH, "w").write("{}")

# 假时钟：每次 now_ts() 前进100秒，让每轮都触发收藏夹同步
clock = {"t": 1000}
vrc_watch.now_ts = lambda: (clock.__setitem__("t", clock["t"] + 100), clock["t"])[1]


def write_cfg():
    with open(vrc_watch.CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump({"poll_seconds": 15, "presence_grace_seconds": 0, "watch_favorites": True,
                   "favorites_sync_seconds": 90, "watch_list": [],
                   "bark": {"enabled": False}, "telegram": {"enabled": False}}, f)


def fr(uid, name):
    return {"id": uid, "displayName": name, "location": "wrld_x:1~hidden",
            "status": "active", "statusDescription": "",
            "last_platform": "standalonewindows", "tags": []}


# 每轮: (收藏夹, 在线好友)
A, C = "usr_a", "usr_c"
SCENARIO = [
    ([A],    [fr(A, "alice"), fr(C, "carol")]),  # 0 启动对账（静默，carol在线但未收藏）
    ([A],    [fr(A, "alice"), fr(C, "carol")]),  # 1 无变化
    ([A, C], [fr(A, "alice"), fr(C, "carol")]),  # 2 carol被收藏（她早已在线）→ 静默登记，不推送
    ([A, C], [fr(A, "alice")]),                  # 3 carol真下线 → 🔴
    ([A, C], [fr(A, "alice"), fr(C, "carol")]),  # 4 carol真上线 → 🟢
    ([],     [fr(A, "alice"), fr(C, "carol")]),  # 5 双双取消收藏（都在线）→ 静默移除，不推送
    ([A],    [fr(A, "alice")]),                  # 6 重新收藏alice（她在线）→ 静默登记，不推送
    ([A],    []),                                # 7 alice真下线 → 🔴
    ([A],    [fr(A, "alice")]),                  # 8 alice真上线 → 🟢
]
FAVS = [s[0] for s in SCENARIO]

pushes = []
state = {"round": 0}


class FakeClient:
    def __init__(self, cfg):
        pass

    def get_friends(self, offline=False):
        if offline:
            return []
        if state["round"] >= len(SCENARIO):
            raise StopIteration
        online = SCENARIO[state["round"]][1]
        state["round"] += 1
        return online

    def get_favorite_friend_ids(self):
        return FAVS[min(state["round"], len(FAVS)) - 1]

    def get_world_name(self, wid, db, cache_only=False):
        return "测试世界" if wid else None


vrc_watch.VRChatClient = FakeClient
# 仿真环境无真实 WS 管线：替换为空操作（本测试只覆盖轮询状态机；WS 管线由 Pi 实机验收覆盖）
vrc_watch.ws_pipeline_thread = lambda *a, **k: None
vrc_watch.push = lambda cfg, title, body: pushes.append(title)
vrc_watch.time.sleep = lambda s: None
# The production waiter now uses Event.wait; exercise state transitions without wall-clock polling.
vrc_watch._wait_wake_or_refresh = lambda wake, delay, last: last

write_cfg()
db = vrc_watch.init_db()
try:
    vrc_watch.watch({"poll_seconds": 15, "presence_grace_seconds": 0, "watch_favorites": True,
                     "favorites_sync_seconds": 90, "watch_list": [],
                     "bark": {"enabled": False}, "telegram": {"enabled": False}}, db)
except StopIteration:
    pass

print("实际推送:", pushes)
expected = ["🔴 carol 下线了", "🟢 carol 上线了", "🔴 alice 下线了", "🟢 alice 上线了"]
missing = [e for e in expected if e not in pushes]
extra = [p for p in pushes if p not in expected]
if missing or extra:
    print(f"❌ 缺失: {missing}  多余: {extra}")
    sys.exit(1)
print("✅ 收藏夹自动跟随逻辑符合预期（加收藏播报/取消收藏停止/无误报）")
