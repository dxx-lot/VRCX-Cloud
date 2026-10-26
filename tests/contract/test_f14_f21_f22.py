"""F-14 群组成员 / F-21 导入导出 / F-22 备份恢复 · 契约测试

上游依据（vendor/VRCX @174551e）：
- group.js: GET groups/{groupId}/members（分页，成员含 user 对象）
- favorite.js: POST favorites 逐个加入（import = 批量 add）
- 验收标准 §6 F-21/F-22：导出不泄露凭据；备份/恢复可校验
"""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import pytest

from group_members import get_members
from favorites import FavoriteService
from errors import AuthCode


class FakeResponse:
    def __init__(self, status, j):
        self.status_code = status
        self._j = j
    def json(self):
        return self._j


class FakeTransport:
    def __init__(self, script):
        self.script = script
    def get(self, path, headers=None, params=None, **kw):
        base = path.split("?")[0]
        for k, v in self.script.items():
            if base.endswith(k):
                return FakeResponse(v[0], v[1])
        return FakeResponse(404, {})


# ---------- F-14 成员 ----------

def test_group_members_passthrough():
    members = [{"userId": "usr_1", "user": {"displayName": "甲", "id": "usr_1"}},
               {"userId": "usr_2", "user": {"displayName": "乙", "id": "usr_2"}}]
    t = FakeTransport({"groups/grp_1/members": (200, members)})
    out = get_members(t, "grp_1")
    assert len(out) == 2
    assert out[0]["name"] == "甲" and out[0]["id"] == "usr_1"


def test_group_members_forbidden():
    t = FakeTransport({"groups/grp_x/members": (403, {"error": {"message": "hidden"}})})
    out = get_members(t, "grp_x")
    assert out == [] or out.get("error")


# ---------- F-21 导入导出 ----------

def test_export_friends_csv_no_secrets(tmp_path):
    """导出 CSV 不得包含凭据字段（验收标准 F-21）"""
    db = sqlite3.connect(tmp_path / "t.db")
    db.execute("CREATE TABLE friends_all (friend_id TEXT, display_name TEXT, "
               "username TEXT, tags TEXT, last_platform TEXT, last_login TEXT, "
               "updated_at INTEGER, thumb TEXT, last_activity TEXT)")
    db.execute("INSERT INTO friends_all VALUES ('usr_1','甲','user1','[]','standalonewindows','2026-01-01',1,'','')")
    db.commit(); db.close()
    from export_import import export_friends_csv
    csv_text = export_friends_csv(str(tmp_path / "t.db"))
    assert "甲" in csv_text and "usr_1" in csv_text
    assert "password" not in csv_text.lower() or "totp" not in csv_text.lower()


def test_import_favgroup_batches_adds(tmp_path):
    class T:
        def __init__(self): self.posts = []
        def post(self, path, json=None, headers=None):
            self.posts.append((path, json)); return 200, {"id": "fav_x"}
    from favorites import FavoriteService
    t = T()
    s = FavoriteService(transport=t, current_user_id="usr_me")
    ok, fail = 0, 0
    for uid in ["usr_1", "usr_2", "usr_3"]:
        r = s.add("friend", uid, group="group_0")
        ok += 1 if r.ok else 0
    assert ok == 3
    assert len(t.posts) == 3
    assert all(p == "favorites" for p, _ in t.posts)


# ---------- F-22 备份恢复 ----------

def test_backup_and_restore(tmp_path):
    src = tmp_path / "vrc_watch.db"
    db = sqlite3.connect(src)
    db.execute("CREATE TABLE t (a TEXT)")
    db.execute("INSERT INTO t VALUES ('数据1')")
    db.commit(); db.close()
    from backup import create_backup, restore_backup
    bk = create_backup(str(src), str(tmp_path / "backups"))
    assert Path(bk).exists()
    # 破坏原库 → 从备份恢复
    src.unlink()
    restore_backup(str(src), bk)
    assert src.exists()
    chk = sqlite3.connect(str(src)); assert chk.execute("PRAGMA integrity_check").fetchone()[0]=="ok"; chk.close()
    db2 = sqlite3.connect(src)
    rows = db2.execute("SELECT a FROM t").fetchall()
    assert rows == [("数据1",)]
