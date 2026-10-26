'上游契约（vendor/VRCX @174551e）：\n- src/plugins/interopApi.js   : 非 Windows 下一切 .NET 类方法经\n  window.interopApi.callDotNetMethod(class, method, argsArray) 走 IPC\n- src/services/sqlite.js      : LINUX 分支 SQLite.ExecuteJson(sql, Map参数)\n  → JSON 行数组字符串（回调按 dbRow[0] 索引访问）；ExecuteNonQuery → 行数\n- src/services/webapi.js      : WebApi.ExecuteJson → {status:int, message:str}\n  JSON 串；ClearCookies/GetCookies/SetCookies\n- src/services/jsonStorage.js : VRCXStorage.Get/Set/Remove/Save/GetAll\n  （GetAll 返回 JSON 串，memoCoordinator.js JSON.parse 消费）\n- Map 参数经 JSON.stringify 会塌缩为 {}，必须先深转换（adapter-shim 同款）。\n\nweb.py 为运行时；本文件为同一契约的可注入测试镜像（tests/contract 消费）。'














import json
import os
import re
import sqlite3
import threading

_UPSTREAM_DEFAULT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "vrcx-upstream.db"))

_AT_PARAM_RE = re.compile(r"[@$]([A-Za-z_][A-Za-z0-9_]*)")
_WRITE_LOCK = threading.Lock()


def _sqlite_translate(sql, args):
    """上游 @name/$name 命名参数 → pysqlite 的 :name（键同步去前缀）。"""
    if isinstance(args, dict):
        sql = _AT_PARAM_RE.sub(r":\1", sql)
        args = {k.lstrip("@$:"): v for k, v in args.items()}
        return sql, args
    return sql, (args or [])


def adapter_sqlite_upstream(payload, db_path=None):
    """SQLite.ExecuteJson：返回行数组的 JSON 串（上游按索引访问）。"""
    db_path = db_path or _UPSTREAM_DEFAULT
    conn = None
    try:
        sql, args = _sqlite_translate(payload.get("sql") or "", payload.get("args"))
        conn = sqlite3.connect(db_path, timeout=15)
        cur = conn.execute(sql, args)
        rows = [list(r) for r in cur.fetchall()]
        conn.commit()
        return {"status": 0, "message": json.dumps(rows, ensure_ascii=False)}
    except Exception as e:
        return {"status": 1, "message": str(e)}
    finally:
        if conn:
            conn.close()


def adapter_sqlite_nonquery(payload, db_path=None):
    """SQLite.ExecuteNonQuery：返回受影响行数 int（写事务串行化）。"""
    db_path = db_path or _UPSTREAM_DEFAULT
    conn = None
    try:
        sql, args = _sqlite_translate(payload.get("sql") or "", payload.get("args"))
        conn = sqlite3.connect(db_path, timeout=15)
        with _WRITE_LOCK:
            cur = conn.execute(sql, args)
            conn.commit()
        return {"status": 0, "message": str(cur.rowcount)}
    except Exception as e:
        return {"status": 1, "message": str(e)}
    finally:
        if conn:
            conn.close()


def _storage_load(storage_path):
    try:
        with open(storage_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _storage_save(storage_path, data):
    tmp = storage_path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, storage_path)


def adapter_dotnet(body, db_path=None, storage_path=None,
                   webapi_fn=None, cookies=None, app_version="unknown"):
    """callDotNetMethod 分发器（与 web.py 同表）。

    webapi_fn(request_json) -> {"status": int, "message": str}（注入会话代理）
    cookies                 -> 带 .clear()/.set(name, value) 且可迭代的会话对象
    """
    db_path = db_path or _UPSTREAM_DEFAULT
    cls = body.get("className") or ""
    meth = body.get("methodName") or ""
    args = body.get("args") or []

    def arg(i):
        return args[i] if len(args) > i else None

    try:
        if cls == "SQLite":
            payload = {"sql": arg(0) or "", "args": arg(1)}
            if meth == "ExecuteJson":
                r = adapter_sqlite_upstream(payload, db_path)
                if r["status"] != 0:
                    raise RuntimeError(r["message"])
                return {"result": r["message"]}
            if meth == "Execute":
                r = adapter_sqlite_upstream(payload, db_path)
                if r["status"] != 0:
                    raise RuntimeError(r["message"])
                return {"result": json.loads(r["message"])}
            if meth == "ExecuteNonQuery":
                r = adapter_sqlite_nonquery(payload, db_path)
                if r["status"] != 0:
                    raise RuntimeError(r["message"])
                return {"result": int(r["message"])}
        elif cls == "WebApi":
            if meth == "ClearCookies":
                cookies.clear()
                return {"result": "cookies cleared"}
            if meth == "GetCookies":
                return {"result": json.dumps(list(cookies))}
            if meth == "SetCookies":
                items = arg(0) or []
                for it in items:
                    if isinstance(it, dict) and it.get("name"):
                        cookies.set(it["name"], str(it.get("value", "")))
                return {"result": f"{len(items)} cookies set"}
            if meth in ("ExecuteJson", "Execute"):
                req = arg(0)
                if meth == "Execute" and isinstance(req, dict):
                    req = json.dumps(req)
                return {"result": json.dumps(webapi_fn(req or ""), ensure_ascii=False)}
        elif cls == "VRCXStorage":
            data = _storage_load(storage_path)
            if meth == "Get":
                return {"result": data.get(arg(0) or "")}
            if meth == "Set":
                data[arg(0) or ""] = str(arg(1))
                _storage_save(storage_path, data)
                return {"result": None}
            if meth == "Remove":
                data.pop(arg(0) or "", None)
                _storage_save(storage_path, data)
                return {"result": None}
            if meth == "GetAll":
                return {"result": json.dumps(data, ensure_ascii=False)}
            if meth == "Save":
                _storage_save(storage_path, data)
                return {"result": None}
        elif cls in ("AppApi", "AppApiElectron", "AppApiVrElectron"):
            if meth == "GetVersion":
                return {"result": app_version}
            return {"result": None}  # 本机能力诚实 null（D-P1-S2/S3）
        elif cls == "LogWatcher":
            if meth == "Get":
                return {"result": []}  # 上游 Linux 语义：空列表可迭代
            return {"result": None}
        elif cls in ("Discord", "AssetBundleManager",
                     "SystemMonitorElectron", "VRCXNetInterface"):
            return {"result": None}
    except Exception as e:
        return {"__error": True, "message": str(e)}
    return {"__error": True, "message": f"{cls}.{meth} not implemented"}
