'离册好友留档 · 契约测试\n\n监控全量同步不再 DELETE 离册好友——改为 in_roster=0 标记保留资料；\nweb 侧 /api/friends 列表只含在册（in_roster=1），详情查询不限\n（历史人物详情秒出+有头像）。'





import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "webui"))

import pytest

import web
import vrc_watch


def _synced(db, uids):
    """复刻监控同步块的关键行为：UPSERT 在册（in_roster=1）+ 离册标 0"""
    import sqlite3
    conn = sqlite3.connect(db)
    for uid in uids:
        conn.execute(
            "INSERT OR REPLACE INTO friends_all "
            "(friend_id,display_name,username,tags,last_platform,"
            "last_login,updated_at,thumb,last_activity,in_roster) "
            "VALUES (?,?,?,?,?,?,?,?,?,1)", (uid, "u_" + uid, "", "[]", "", "", 0, "", "", 1))
    ph = ",".join("?" * len(uids)) if uids else None
    if uids:
        conn.execute(f"UPDATE friends_all SET in_roster=0 WHERE friend_id NOT IN ({ph})", uids)
    else:
        conn.execute("UPDATE friends_all SET in_roster=0 WHERE in_roster=1")
    conn.commit()
    conn.close()


def test_vrc_watch_sync_marks_gone_friends():
    """监控源码必须包含离册标记逻辑（防回退到 DELETE 旧行为）"""
    src = (Path(__file__).resolve().parents[2] / "src" / "webui" / "vrc_watch.py").read_text(encoding="utf-8")
    assert "UPDATE friends_all SET in_roster=0" in src
    assert "WHERE friend_id NOT IN ({ph})" in src
    assert src.count("DELETE FROM friends_all") == 0, "不应再物理删除好友资料"


def test_web_friends_list_roster_only():
    src = (Path(__file__).resolve().parents[2] / "src" / "webui" / "web.py").read_text(encoding="utf-8")
    assert "FROM friends_all WHERE in_roster=1 ORDER BY display_name" in src
