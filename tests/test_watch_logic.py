#!/usr/bin/env python3
# 仿真测试：用假数据驱动 vrc_watch.watch()，验证上/下线通知逻辑
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


def write_cfg(watch_list):
    with open(vrc_watch.CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump({"poll_seconds": 15, "presence_grace_seconds": 0, "watch_list": watch_list,
                   "bark": {"enabled": False}, "telegram": {"enabled": False}}, f)


def fr(uid, name, loc="wrld_x:123~hidden"):
    return {"id": uid, "displayName": name, "location": loc, "status": "active",
            "statusDescription": "", "last_platform": "standalonewindows", "tags": []}


ROUNDS = [
    [fr("usr_a", "alice")],                          # 0 启动对账（静默）
    [fr("usr_a", "alice")],                          # 1 仍在线
    [],                                              # 2 alice 下线  → 🔴
    [fr("usr_a", "alice")],                          # 3 alice 重新上线 → 🟢（原 bug 会漏）
    [fr("usr_a", "alice"), fr("usr_c", "carol")],    # 4 carol 在线（尚未关注）
    [fr("usr_a", "alice"), fr("usr_c", "carol")],    # 5 关注 carol（应静默，不误报）
    [fr("usr_a", "alice")],                          # 6 carol 下线 → 🔴
    [fr("usr_a", "alice"), fr("usr_c", "carol")],    # 7 carol 重新上线 → 🟢
]

pushes = []
state = {"round": 0}


class FakeClient:
    def __init__(self, cfg):
        pass

    def get_friends(self, offline=False):
        if offline:
            return []
        if state["round"] >= len(ROUNDS):
            raise StopIteration
        batch = ROUNDS[state["round"]]
        print(f"  [round {state['round']}] online={[f['displayName'] for f in batch]}", flush=True)
        state["round"] += 1
        if state["round"] == 5:          # carol 在线时加入关注名单
            write_cfg(["alice", "carol"])
        return batch

    def get_favorite_friend_ids(self):
        return []

    def get_world_name(self, wid, db, cache_only=False):
        return "测试世界" if wid else None


vrc_watch.VRChatClient = FakeClient
# 仿真环境无真实 WS 管线：替换为空操作（本测试只覆盖轮询状态机；WS 管线由 Pi 实机验收覆盖）
vrc_watch.ws_pipeline_thread = lambda *a, **k: None
vrc_watch.push = lambda cfg, title, body: pushes.append(title)
vrc_watch.time.sleep = lambda s: None
# The production waiter now uses Event.wait; exercise state transitions without wall-clock polling.
vrc_watch._wait_wake_or_refresh = lambda wake, delay, last: last

write_cfg(["alice"])
db = vrc_watch.init_db()
try:
    vrc_watch.watch({"poll_seconds": 15, "presence_grace_seconds": 0, "watch_list": ["alice"],
                     "bark": {"enabled": False}, "telegram": {"enabled": False}}, db)
except StopIteration:
    pass

print("实际推送:", pushes)
expected = ["🔴 alice 下线了", "🟢 alice 上线了", "🔴 carol 下线了", "🟢 carol 上线了"]
missing = [e for e in expected if e not in pushes]
extra = [p for p in pushes if p not in expected]
if missing or extra:
    print(f"❌ 缺失: {missing}  多余: {extra}")
    sys.exit(1)
print("✅ 全部符合预期")
