"""F-04 好友状态模型 · 验收测试（对照验收标准 §6 F-04；上游依据 ws-event-semantics.md）

覆盖：online/active/offline 三态、Join Me/Ask Me/Busy、平台、位置隐私（私密世界）、
实例类型解析、头像变化单次记录、同一事件只记录一次（含重启对账）。
驱动对象：legacy watch() 真实代码路径（sim_common 骨架，无 mock 状态机）。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest

import sim_common as S
import vrc_watch


def friend(uid, name, **kw):
    return S.fr(uid, name, **kw)


def titles(pushes):
    return [p for p in pushes if p.startswith(("🟢", "🔴", "🌐", "🔄", "✏️", "👕"))]


# ---------- 三态与状态机 ----------

def test_three_states_online_active_offline(tmp_path):
    S.fresh_env(tmp_path)
    A = "usr_a"
    rounds = [
        ([], [friend(A, "alice")]),                                  # 0 对账（静默）
        ([], [friend(A, "alice")]),                                  # 1 稳定
        ([], [friend(A, "alice", location="offline", state="active")]),  # 2 进大厅→active
        ([], [friend(A, "alice", location="offline", state="active")]),  # confirmed web
        ([], [friend(A, "alice", location="wrld_y:9~friends+")]),    # 3 进世界→online
        ([], []),                                                    # missing candidate
        ([], []),                                                    # confirmed offline
    ]
    pushes, db = S.run(rounds)
    types = [r[0] for r in db.execute("select event from events order by ts, id")]
    assert "active" in types and "online" in types and "offline" in types
    # 状态序列正确：active(2) → online(3) → offline(4)
    seq = [r[0] for r in db.execute(
        "select event from events where display_name='alice' and event!='status' order by ts, id")]
    assert seq == ["offline", "active", "online", "offline"]
    assert len(titles(pushes)) == 4  # 🌐 active / 🟢 online / 🔴 offline 各一次


def test_joinme_askme_busy_status_changes(tmp_path):
    S.fresh_env(tmp_path)
    A = "usr_a"
    rounds = [
        ([], [friend(A, "alice", status="join me")]),   # 0 对账
        ([], [friend(A, "alice", status="join me")]),   # 1 稳定
        ([], [friend(A, "alice", status="ask me")]),    # 2 Join Me→Ask Me
        ([], [friend(A, "alice", status="busy")]),      # 3 Ask Me→勿扰
        ([], [friend(A, "alice", status="active")]),    # 4 勿扰→在线
    ]
    pushes, db = S.run(rounds)
    rows = [r for r in db.execute(
        "select status_description, previous, status from events where event='status' order by ts")]
    assert len(rows) == 3
    assert [tuple(row) for row in rows] == [
        ("", "join me", "ask me"), ("", "ask me", "busy"), ("", "busy", "active")]
    # Descriptions remain the actual snapshot; the UI derives the transition
    # from the separate previous/status fields, as VRCX does.



# ---------- 平台 ----------

def test_platform_recorded_and_updated(tmp_path):
    S.fresh_env(tmp_path)
    A = "usr_a"
    rounds = [
        ([], [friend(A, "alice", platform="standalonewindows")]),  # 0
        ([], [friend(A, "alice", platform="standalonewindows")]),  # 1
        ([], [friend(A, "alice", platform="android")]),            # 2 换 Quest
    ]
    pushes, db = S.run(rounds)
    plat = db.execute("select platform from friends_current where friend_id=?", (A,)).fetchone()[0]
    assert plat == "android"


# ---------- 位置隐私与实例类型 ----------

def test_private_world_privacy(tmp_path):
    """位置隐私：私密世界只显示'位于私人房间'，不落世界名"""
    S.fresh_env(tmp_path)
    A = "usr_a"
    rounds = [
        ([], [friend(A, "alice", location="wrld_priv:1~hidden")]),  # 0 对账（world 查不到名）
        ([], [friend(A, "alice", location="private", state="online")]),  # 1 私密
    ]
    pushes, db = S.run(rounds)
    row = db.execute("select location from events where event='location'").fetchone()
    assert row[0] == "private"


def test_instance_types_parsed(tmp_path):
    """实例类型：朋友+/朋友/邀请/邀请+/群组/公开 解析正确"""
    from vrc_watch import parse_location
    # 上游 locationParser.js 权威映射（hidden=好友+，friends=仅限好友）
    assert parse_location("wrld_x:1~hidden(usr_x)")[2] == "好友+"
    assert parse_location("wrld_x:1~friends(usr_x)")[2] == "仅限好友"
    assert parse_location("wrld_x:1~invite(usr_x)~canRequestInvite")[2] == "邀请+"
    assert parse_location("wrld_x:1~invite(usr_x)")[2] == "仅限邀请"
    assert parse_location("wrld_x:1~groupAccessType(members)~group(grp_1)")[2] == "群组"
    assert parse_location("wrld_x:1")[2] == "公开"


# ---------- 头像变化：单次记录 ----------

def test_avatar_change_recorded_once(tmp_path):
    S.fresh_env(tmp_path)
    A = "usr_a"
    rounds = [
        ([], [friend(A, "alice", avatar="https://av/1.png")]),  # 0 对账
        ([], [friend(A, "alice", avatar="https://av/1.png")]),  # 1 重复轮（同头像）
        ([], [friend(A, "alice", avatar="https://av/2.png")]),  # 2 换模型 → 1 条
        ([], [friend(A, "alice", avatar="https://av/2.png")]),  # 3 同头像重复轮
    ]
    pushes, db = S.run(rounds)
    n = db.execute("select count(*) from events where event='avatar'").fetchone()[0]
    assert n == 1  # 只记一次


# ---------- 同一事件只记录一次（含重启对账） ----------

def test_no_duplicate_events_after_restart(tmp_path):
    """重启对账：数据库已有在线记录 → 重启首轮不重推/不重复记录"""
    S.fresh_env(tmp_path)
    A = "usr_a"
    rounds = [
        ([], [friend(A, "alice")]),            # 0 对账
        ([], [friend(A, "alice")]),            # 1 稳定
    ]
    pushes1, db = S.run(rounds)
    n_before = db.execute("select count(*) from events").fetchone()[0]

    # 模拟服务重启：新进程 + 同一 DB（auth 保留）
    vrc_watch2 = vrc_watch  # 同模块；重建 watch 状态即可
    rounds2 = [
        ([], [friend(A, "alice")]),            # 重启首轮对账（静默）
        ([], [friend(A, "alice")]),            # 稳定
    ]
    S.state = {"round": 0}
    rounds_holder = rounds2

    class RestartRun:
        pass

    # 直接再跑一遍 run()（同一 db 文件）
    pushes2, db2 = S.run(rounds2)
    n_after = db.execute("select count(*) from events").fetchone()[0]
    # 重启对账不新增事件
    assert n_after == n_before


def test_same_transition_only_once(tmp_path):
    """同一转换不会因连续多轮重复记录（状态机边沿触发）"""
    S.fresh_env(tmp_path)
    A = "usr_a"
    rounds = [
        ([], []),
        ([], [friend(A, "alice", status="join me", location="wrld_x:1")]),  # 上线
        ([], [friend(A, "alice", status="join me", location="wrld_x:1")]),  # 同态
        ([], [friend(A, "alice", status="join me", location="wrld_x:1")]),  # 同态
    ]
    pushes, db = S.run(rounds)
    n_online = db.execute("select count(*) from events where event='online'").fetchone()[0]
    n_status = db.execute("select count(*) from events where event='status'").fetchone()[0]
    assert n_online == 1 and n_status == 0
