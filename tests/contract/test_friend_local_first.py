'用户详情本地优先（VRCX 同款）· 契约测试\n\napi_friend 取用顺序：5min 缓存 → 本地镜像秒出（标 stale，后台线程刷新 live）\n→ 无本地数据（非好友直链）才阻塞 live。\n镜像 user 形状必须与 live 一致（前端标签页直接消费）。'





import json
import sqlite3
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src" / "webui"))

import pytest

import web
from services.session import Refresher


def held_refresh(monkeypatch):
    refresher = Refresher()
    started = []
    # Hold the executor, keeping the actual production admission/deduplication.
    monkeypatch.setattr(refresher._pool, 'submit', lambda work: started.append(work))
    monkeypatch.setattr(web, '_REFRESHER', refresher)
    return started


@pytest.fixture()
def friend_db(monkeypatch, tmp_path):
    dbp = tmp_path / "vrc_watch.db"
    conn = sqlite3.connect(dbp)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE friends_all (friend_id TEXT, display_name TEXT, username TEXT,"
                 "tags TEXT, last_platform TEXT, last_login TEXT, updated_at REAL,"
                 "thumb TEXT, last_activity TEXT)")
    conn.execute("CREATE TABLE friends_current (friend_id TEXT, display_name TEXT,"
                 "online_since REAL, location TEXT, world_name TEXT, status TEXT,"
                 "desc TEXT, platform TEXT, tags TEXT, state TEXT, avatar TEXT)")
    conn.execute("CREATE TABLE events (friend_id TEXT, display_name TEXT, event TEXT,"
                 "ts REAL, duration REAL, world_name TEXT, location TEXT, status TEXT,"
                 "status_description TEXT, platform TEXT)")
    conn.execute("CREATE TABLE worlds (world_id TEXT, name TEXT, fetched_at REAL)")
    now = time.time()
    conn.execute("INSERT INTO friends_all VALUES ('usr_f1','测试仔','tester','[]','pc',"
                 "'2026-10-05T10:00:00Z',?, 'https://cdn/t.png','2026-10-06T09:00:00Z')", (now,))
    conn.execute("INSERT INTO friends_current VALUES ('usr_f1','测试仔',?,"
                 "'wrld_x:1','世界X','active','来玩','pc','[]','online','avtr_x')", (now - 600,))
    conn.execute("INSERT INTO events VALUES ('usr_f1','测试仔','online',?,NULL,'世界X',"
                 "'wrld_x:1','active','来玩','pc')", (now - 600,))
    conn.execute("INSERT INTO worlds VALUES ('wrld_x','世界X',?)", (now - 86400,))
    conn.commit()
    conn.close()
    monkeypatch.setattr(web, "DB_PATH", str(dbp))
    return dbp


def test_local_payload_shape(friend_db):
    out = web._friend_local_payload("usr_f1")
    assert out and out["stale"] is True
    u = out["user"]
    assert u["displayName"] == "测试仔"
    assert u["currentAvatarThumbnailImageUrl"] == "https://cdn/t.png"
    assert u["state"] == "online" and u["world"] == "世界X" and u["world_id"] == "wrld_x"
    assert u["isFriend"] is True and u["trust"]["name"]
    assert out["groups"] == [] and out["live"] is None
    assert len(out["events"]) == 1


def test_local_payload_none_for_unknown(friend_db):
    assert web._friend_local_payload("usr_ghost") is None


def test_api_friend_fast_path_returns_local_and_caches(monkeypatch, friend_db):
    web._friend_cache.clear()
    started = held_refresh(monkeypatch)

    def fake_live(uid):
        return {"user": {"id": uid, "displayName": "测试仔"}, "stale": False, "events": [],
                "groups": [], "worlds_created": [], "avatars_created": [], "live": None,
                "heat": [], "logins30": 0, "hours30": 0, "raw": {}, "last_room": None,
                "mutual": {"counts": [], "friends": []}}

    monkeypatch.setattr(web, "_friend_live", fake_live)
    r1 = web.api_friend("usr_f1")
    assert r1["stale"] is True                        # 本地镜像秒出
    assert web._friend_cache["usr_f1"][1]["stale"]    # 已入缓存
    assert web.api_friend("usr_f1")["stale"] is True  # 5min 内命中缓存
    assert len(started) == 1                          # 恰好一个后台刷新线程
    started[0]()                                      # 手动执行后台目标
    assert web._friend_cache["usr_f1"][1]["stale"] is False  # live 覆盖本地


def test_api_friend_repeated_snapshot_does_not_schedule_another_refresh(monkeypatch, friend_db):
    web._friend_cache.clear()
    submitted = held_refresh(monkeypatch)
    for _ in range(10):
        assert web.api_friend("usr_f1")["stale"]
    assert len(submitted) == 1


def test_api_friend_falls_back_to_live_without_local(monkeypatch, tmp_path):
    dbp = tmp_path / "empty.db"
    conn = sqlite3.connect(dbp)
    conn.execute("CREATE TABLE friends_all (friend_id TEXT, display_name TEXT, username TEXT,"
                 "tags TEXT, last_platform TEXT, last_login TEXT, updated_at REAL,"
                 "thumb TEXT, last_activity TEXT)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(web, "DB_PATH", str(dbp))
    web._friend_cache.clear()

    def fake_live(uid):
        return {"user": {"id": uid}, "events": [], "groups": [], "worlds_created": [],
                "avatars_created": [], "live": None, "heat": [], "logins30": 0,
                "hours30": 0, "raw": {}, "last_room": None,
                "mutual": {"counts": [], "friends": []}}

    monkeypatch.setattr(web, "_friend_live", fake_live)
    r = web.api_friend("usr_nolocal")
    assert "stale" not in r                           # 无本地数据 → 阻塞 live，不标 stale


def test_persisted_personal_detail_is_only_reused_for_the_current_identity(friend_db):
    web._ensure_scope()
    web._self_cache.update(data={'id':'usr_owner_A'},ts=time.time())
    payload={'_account_id':'usr_owner_A','user':{'id':'usr_f1','displayName':'cached-A','note':'private test note'}}
    with sqlite3.connect(friend_db) as conn:
        conn.execute('CREATE TABLE user_cache (uid TEXT PRIMARY KEY,payload TEXT,ts REAL)')
        conn.execute('INSERT INTO user_cache VALUES (?,?,?)',('usr_f1',json.dumps(payload),time.time()))
    assert web._friend_local_payload('usr_f1')['user']['displayName'] == 'cached-A'
    web._self_cache.update(data={'id':'usr_owner_B'},ts=time.time())
    # Existing friendship snapshot remains available; personal cached note is discarded.
    result=web._friend_local_payload('usr_f1')
    assert result['user']['displayName'] == '测试仔'
    assert result['user'].get('note') != 'private test note'
