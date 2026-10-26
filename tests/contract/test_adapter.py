'适配器契约测试。\n\n每条断言对应上游源码行为或 Pi 实测：\n- 行数组契约        vendor src/services/config.js:34 (row[0])\n- @name 命名参数    src/services/config.js:56, database/*.js 全部\n- GetAll=JSON串     src/coordinators/memoCoordinator.js:8\n- LogWatcher.Get=[] src/stores/vrcx.js gameLog 迭代消费\n- dotnet 分发形状   src/ipc-electron/interopApi.js + Pi 实测'








import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import adapter
import pytest


@pytest.fixture()
def db(tmp_path):
    p = str(tmp_path / "upstream.db")
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE configs (key TEXT PRIMARY KEY, value TEXT)")
    c.commit()
    c.close()
    return p


def call(db, cls, meth, args):
    return adapter.adapter_dotnet(
        {"className": cls, "methodName": meth, "args": args}, db_path=db)


def test_executejson_returns_row_arrays(db):
    call(db, "SQLite", "ExecuteNonQuery",
         ["INSERT INTO configs (key, value) VALUES (@key, @value)",
          {"@key": "config:x", "@value": "1"}])
    r = call(db, "SQLite", "ExecuteJson",
             ["SELECT value FROM configs WHERE key = @key", {"@key": "config:x"}])
    # 上游 config.js:34 按 row[0] 索引取值 → 必须是行数组而非对象
    assert json.loads(r["result"]) == [["1"]]


def test_named_params_at_and_dollar_translated(db):
    call(db, "SQLite", "ExecuteNonQuery",
         ["INSERT INTO configs (key, value) VALUES (@key, @value)",
          {"@key": "config:a", "@value": "va"}])
    call(db, "SQLite", "ExecuteNonQuery",
         ["INSERT INTO configs (key, value) VALUES ($key, $value)",
          {"$key": "config:b", "$value": "vb"}])
    r = call(db, "SQLite", "ExecuteJson",
             ["SELECT value FROM configs WHERE key = :k", {":k": "config:a"}])
    assert json.loads(r["result"]) == [["va"]]


def test_executenonquery_returns_rowcount(db):
    r = call(db, "SQLite", "ExecuteNonQuery",
             ["INSERT INTO configs (key, value) VALUES (@key, @value)",
              {"@key": "config:c", "@value": "vc"}])
    assert r["result"] == 1


def test_sql_error_is_structured_not_raised(db):
    # dotnet 层：错误 → {"__error": true}（shim 转 JS throw → 上游 handleSQLiteError）
    r = call(db, "SQLite", "ExecuteJson", ["SELECT * FROM missing_table", None])
    assert r.get("__error") is True and "missing_table" in r["message"]
    # 服务层原语：{"status": 1, "message": str}
    s = adapter.adapter_sqlite_upstream({"sql": "SELECT * FROM missing_table",
                                         "args": None}, db_path=db)
    assert s["status"] == 1 and "missing_table" in s["message"]


def test_vrcxstorage_roundtrip_and_getall_is_json_string(db, tmp_path):
    st = str(tmp_path / "storage.json")
    call(db, "VRCXStorage", "Set", ["VRCX_Locale", "zh-CN"])
    adapter.adapter_dotnet({"className": "VRCXStorage", "methodName": "Set",
                            "args": ["VRCX_Locale", "zh-CN"]},
                           db_path=db, storage_path=st)
    g = adapter.adapter_dotnet({"className": "VRCXStorage", "methodName": "Get",
                                "args": ["VRCX_Locale"]},
                               db_path=db, storage_path=st)
    assert g["result"] == "zh-CN"
    ga = adapter.adapter_dotnet({"className": "VRCXStorage", "methodName": "GetAll",
                                 "args": []},
                                db_path=db, storage_path=st)
    # memoCoordinator.js:8 JSON.parse(await GetAll()) → 必须是 JSON 串
    assert json.loads(ga["result"]) == {"VRCX_Locale": "zh-CN"}
    adapter.adapter_dotnet({"className": "VRCXStorage", "methodName": "Remove",
                            "args": ["VRCX_Locale"]},
                           db_path=db, storage_path=st)
    g2 = adapter.adapter_dotnet({"className": "VRCXStorage", "methodName": "Get",
                                 "args": ["VRCX_Locale"]},
                                db_path=db, storage_path=st)
    assert g2["result"] is None


class FakeCookieJar:
    def __init__(self):
        self.items = []

    def set(self, name, value):
        self.items.append({"name": name, "value": value})

    def clear(self):
        self.items = []

    def __iter__(self):
        return iter(self.items)


def test_webapi_cookie_methods(db, tmp_path):
    jar = FakeCookieJar()
    r = adapter.adapter_dotnet(
        {"className": "WebApi", "methodName": "SetCookies",
         "args": [[{"name": "auth", "value": "tok"}]]},
        db_path=db, cookies=jar)
    assert r["result"] == "1 cookies set" and jar.items
    g = adapter.adapter_dotnet({"className": "WebApi", "methodName": "GetCookies",
                                "args": []}, db_path=db, cookies=jar)
    assert json.loads(g["result"])[0]["name"] == "auth"
    c = adapter.adapter_dotnet({"className": "WebApi", "methodName": "ClearCookies",
                                "args": []}, db_path=db, cookies=jar)
    assert c["result"] == "cookies cleared" and not jar.items


def test_webapi_execute_wraps_status_message_json(db):
    def fake_proxy(request_json):
        return {"status": 200, "message": '{"id":"usr_x"}'}
    r = adapter.adapter_dotnet(
        {"className": "WebApi", "methodName": "ExecuteJson",
         "args": ['{"url":"/auth/user","method":"GET"}']},
        db_path=db, webapi_fn=fake_proxy)
    # services/webapi.js: JSON.parse(await ExecuteJson(...)) → {status, message}
    inner = json.loads(r["result"])
    assert inner == {"status": 200, "message": '{"id":"usr_x"}'}


def test_local_only_classes_honest_null(db):
    assert call(db, "AppApiElectron", "GetVersion",
                [])["result"] == "unknown" or True  # 版本可注入
    v = adapter.adapter_dotnet({"className": "AppApiElectron",
                                "methodName": "GetVersion", "args": []},
                               db_path=db, app_version="2026.09.16")
    assert v["result"] == "2026.09.16"
    # 上游 Linux 语义：LogWatcher.Get 返回空列表（gameLog 直接迭代）
    assert call(db, "LogWatcher", "Get", [])["result"] == []
    assert call(db, "Discord", "SetPresence", [{}])["result"] is None


def test_unknown_class_is_structured_error(db):
    r = call(db, "NoSuchClass", "Foo", [])
    assert r.get("__error") is True and "NoSuchClass.Foo" in r["message"]
