'F-03 实时管线 · 回放测试\n\n上游依据（vendor/VRCX @174551e）：\n- services/websocket.js:127-130 字节级重复丢弃\n- services/websocket.js:103-108 固定 5000ms 重连\n- services/websocket.js:75-82     非优雅重连成功 → refreshNotifications+refreshFriends（对账）\n- services/websocket.js:287-356   friend-online/location/active/offline/update 状态语义\n- services/database/feed.js        INSERT OR IGNORE + created_at 唯一（重复只落一条）\n\n本文件在 backend/ws_events.py 存在前必须全红。'











import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import pytest

from ws_events import WsPipeline, ReconnectPolicy, InMemoryFeed


def ev(t, **kw):
    """构造上游管线消息（content 为 JSON 字符串，websocket.js:131-137 二次解析）"""
    import json
    msg = {"type": t, "content": json.dumps(kw)}
    return msg


U1 = "usr_aaa"


def friend_msg(t, uid=U1, name="alice", location=None, status=None, desc=None, avatar=None, **user_extra):
    user = {"id": uid, "displayName": name}
    if status is not None: user["status"] = status
    if desc is not None: user["statusDescription"] = desc
    if avatar is not None: user["currentAvatarImageUrl"] = avatar
    user.update(user_extra)
    kw = {"userId": uid, "user": user}
    if location is not None: kw["location"] = location
    return ev(t, **kw)


# ---------- 1. 事件语义（semantics） ----------

def test_friend_online_sets_online_with_location():
    p = WsPipeline(feed=InMemoryFeed())
    p.apply(friend_msg("friend-online", location="wrld_x:1~region(eu)"))
    assert p.state[U1]["state"] == "online"
    assert p.state[U1]["location"] == "wrld_x:1~region(eu)"


def test_friend_location_forces_online_jank():
    """上游 :358-389: friend-location 强制 state='online'（源码注释 JANK）"""
    p = WsPipeline(feed=InMemoryFeed())
    p.state[U1] = {"state": "active", "location": "offline"}
    p.apply(friend_msg("friend-location", location="wrld_y:2"))
    assert p.state[U1]["state"] == "online"
    assert p.state[U1]["location"] == "wrld_y:2"


def test_friend_active_sets_active_and_location_offline():
    p = WsPipeline(feed=InMemoryFeed())
    p.state[U1] = {"state": "online", "location": "wrld_x:1"}
    p.apply(friend_msg("friend-active"))
    assert p.state[U1]["state"] == "active"
    assert p.state[U1]["location"] == "offline"


def test_friend_offline_only_needs_userid():
    p = WsPipeline(feed=InMemoryFeed())
    p.state[U1] = {"state": "online", "location": "wrld_x:1"}
    p.apply(ev("friend-offline", userId=U1))  # 无 user 对象
    assert p.state[U1]["state"] == "offline"
    assert p.state[U1]["location"] == "offline"


def test_friend_update_only_fields_not_state():
    p = WsPipeline(feed=InMemoryFeed())
    p.state[U1] = {"state": "online", "location": "wrld_x:1", "status": "active"}
    p.apply(friend_msg("friend-update", status="join me", desc="来玩"))
    assert p.state[U1]["state"] == "online"           # 状态不动
    assert p.state[U1]["location"] == "wrld_x:1"      # 位置不动
    assert p.state[U1]["status"] == "join me"         # 字段更新
    assert p.state[U1]["desc"] == "来玩"


def test_content_parse_failure_ignored_not_crash():
    """上游 :135-137 解析失败静默忽略，不得崩溃"""
    p = WsPipeline(feed=InMemoryFeed())
    p.apply({"type": "friend-online", "content": "{not-json"})   # 不崩
    p.apply({"type": "unknown-type", "content": "{}"})           # 未知类型忽略
    assert U1 not in p.state


# ---------- 2. 重复（duplicate suppression） ----------

def test_byte_identical_message_dropped():
    """上游 :127-130 上一条字节级相同 → 丢弃（连 feed 都不写）"""
    p = WsPipeline(feed=InMemoryFeed())
    msg = friend_msg("friend-online", location="wrld_x:1")
    p.apply(msg)
    p.apply(msg)   # 完全相同
    assert len(p.feed.rows) == 1


def test_same_created_at_event_ignored_in_feed():
    """上游 feed.js：INSERT OR IGNORE + created_at 唯一 → 重放只落一条"""
    p = WsPipeline(feed=InMemoryFeed())
    now = 1700000000
    with_time = lambda m: {**m, "_ts": now}
    p.apply(with_time(friend_msg("friend-online", location="wrld_x:1")))
    p.apply(with_time(friend_msg("friend-online", location="wrld_x:1")))  # 同 ts 重放
    assert len(p.feed.rows) == 1


# ---------- 3. 乱序（out-of-order） ----------

def test_out_of_order_last_write_wins_state_feed_sorted_by_created_at():
    """上游不防乱序：状态=最后到达者；feed 按 created_at 排序展示"""
    p = WsPipeline(feed=InMemoryFeed())
    t_on, t_off = 1700000000, 1700000060
    # 网络重放：offline（晚发生）先到，online（早发生）后到
    # 修正：直接用 _ts 注入
    p2 = WsPipeline(feed=InMemoryFeed())
    m_off = ev("friend-offline", userId=U1); m_off["_ts"] = t_off
    m_on = friend_msg("friend-online", location="wrld_x:1"); m_on["_ts"] = t_on
    p2.apply(m_off)
    p2.apply(m_on)
    assert p2.state[U1]["state"] == "online"   # 最后到达者赢
    # feed 展示序：晚的在前（created_at DESC）
    ts_list = [r["created_at"] for r in p2.feed.rows]
    assert ts_list == sorted(ts_list, reverse=True)




def test_reconnect_after_5s_fixed_like_upstream():
    pol = ReconnectPolicy()
    assert pol.next_delay(after_success=True) == 5.0     # 上游固定 5000ms


def test_backoff_5_30_60_cap_then_reset(D=None):
    
    pol = ReconnectPolicy()
    assert pol.next_delay(after_success=False) == 5.0
    assert pol.next_delay(after_success=False) == 30.0
    assert pol.next_delay(after_success=False) == 60.0
    assert pol.next_delay(after_success=False) == 60.0   # 封顶
    assert pol.next_delay(after_success=True) == 5.0     # 复位


def test_pipeline_reconnect_triggers_reconcile_only_after_abnormal_close():
    """上游 :75-82：非优雅关闭后的重连成功 → 对账（refresh）"""
    p = WsPipeline(feed=InMemoryFeed())
    p.on_close(1006)              # 异常关闭
    assert p.closed_gracefully is False
    reconciled = []
    p.on_reconnect(callback=lambda: reconciled.append(1))
    p.on_open()                   # 重连成功
    assert reconciled == [1]
    # 优雅关闭后的重连不触发对账
    p.on_close(1000)
    assert p.closed_gracefully is True
    p.on_open()
    assert reconciled == [1]      # 没有新增
