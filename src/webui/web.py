#!/usr/bin/env python3

# -*- coding: utf-8 -*-

'Single-account HTTP service used by the VRCX Cloud application gateway.'







import json
from pathlib import Path
from copy import deepcopy
from services.assets import Assets
from services.session import SessionScope, SingleFlight, Refresher
from services.feed import FeedRepository, project_session_durations
from services.peer import relay_url
from services.routes import ApiRouter
from services.cache import ResponseCache
from services.media import MediaCache, MEDIA_PATH, image_type

import os
import sys

# Repository and release layouts both use the same domain service modules.
_RUNTIME_DIR = Path(__file__).resolve().parent
for _candidate in (_RUNTIME_DIR / "domain", _RUNTIME_DIR.parent.parent / "backend", _RUNTIME_DIR):
    if (_candidate / "favorites.py").is_file():
        sys.path.insert(0, str(_candidate))
        break

import gzip
import io
import re

import sqlite3

import threading

import time

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from urllib.parse import parse_qs, urlparse

import requests

import vrc_watch

from vrc_watch import (AUTH_PATH, BASE, DB_PATH, CONFIG_PATH, TwoFactorRequired,

                       VRChatClient as _VRChatClient, DIR, init_db, load_config, log, parse_location,

                       push, trust_rank)

_lock = threading.Lock()

_login_ctx = {}

_self_cache = {"ts": 0, "data": None}

_world_cache = {}  # world_id -> (ts, dict)
_MEDIA = None

def _image_scope():
    try:
        info = os.stat(AUTH_PATH)
        stamp = (info.st_ino, info.st_mtime_ns, info.st_size)
    except OSError:
        stamp = None
    return repr((os.path.realpath(DB_PATH), os.path.realpath(AUTH_PATH), stamp))

def _image_cache():
    global _MEDIA
    root = Path(DB_PATH).parent / 'image-cache'
    with _lock:
        if _MEDIA is None or _MEDIA.root != root:
            _MEDIA = MediaCache(root)
        return _MEDIA

def api_image(qs):
    url = (qs.get('url') or [''])[0]
    scope = _image_scope()
    try:
        result = _image_cache().get(scope, url, lambda:VRChatClient(load_config()).s)
        if scope != _image_scope(): return {'error':'账号会话已变更，请刷新'}
        return result
    except (ValueError, OSError, requests.RequestException):
        return {'error':'图片暂不可用'}
def _upstream_db_path():
    if os.environ.get("VRCX_PI_STATE_DIR"):
        return os.path.join(DIR, "vrcx-upstream.db")
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [os.path.join(here, "vrcx-upstream.db"),
             os.path.join(here, "..", "..", "vrcx-upstream.db")]
    for c in cands:
        p = os.path.normpath(c)
        if os.path.isfile(p):
            return p
    return os.path.normpath(cands[0])

UPSTREAM_DB_PATH = _upstream_db_path()

_mutual_cache = {}  # 共同好友图缓存（15 分钟，防 60+ 请求打爆限流）

_status_cache = {"ts": 0, "logged": False, "auth_mtime": 0}

CFG_FIELDS = {  # 设置页允许修改的字段: key路径 -> (类型, 默认值)

    "bark.enabled": bool, "bark.level": str, "bark.sound": str,

    "bark.group": str, "bark.critical_volume": int,

    "telegram.enabled": bool, "telegram.bot_token": str, "telegram.chat_id": str,

    "watch_favorites": bool, "notify_online": bool, "notify_offline": bool,

    "notify_world_change": bool, "notify_active": bool, "notify_active_offline": bool, "notify_status": bool,

    "notify_desc": bool, "notify_avatar": bool,

    "poll_seconds": int, "favorites_sync_seconds": int,

}

def db_ro():

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)

    conn.row_factory = sqlite3.Row

    return conn

_SESSION_SCOPE = SessionScope()
_FLIGHTS = SingleFlight()
_REFRESHER = Refresher(workers=2)
_RESPONSES = ResponseCache(_REFRESHER)
_CACHE_EPOCH = None


def _ensure_scope():
    global _CACHE_EPOCH
    epoch = _SESSION_SCOPE.current(AUTH_PATH, DB_PATH)
    with _SESSION_SCOPE.lock:
        if epoch != _CACHE_EPOCH:
            _RESPONSES.clear()
            _self_cache.update(ts=0, data=None)
            _status_cache.update(ts=0, logged=False, auth_mtime=0)
            _world_cache.clear(); _mutual_cache.clear()
            globals().get("_instance_cache", {}).clear()
            globals().get("_friend_cache", {}).clear()
            globals().get("_ACCT_CACHE", {}).update(ts=0, data={}, uid=None)
            if "_UI_SESSION" in globals():
                _UI_SESSION["client"] = None
            _CACHE_EPOCH = epoch
    return epoch


def _invalidate_session():
    _SESSION_SCOPE.invalidate()
    _ensure_scope()


def VRChatClient(cfg):
    """Every web client belongs to the session which created it, even nested calls."""
    epoch = _ensure_scope()
    client = _VRChatClient(cfg)
    client._web_epoch = epoch
    return client


def _client_epoch(client):
    current = _ensure_scope()
    return current if getattr(client, "_web_epoch", current) == current else None


def check_logged(cfg):
    epoch = _ensure_scope()
    if not os.path.exists(AUTH_PATH):
        return False
    with _SESSION_SCOPE.lock:
        if _status_cache["ts"] and time.time() - _status_cache["ts"] < 60:
            return _status_cache["logged"]
    ok = bool(get_self(VRChatClient(cfg)))
    with _SESSION_SCOPE.lock:
        if epoch != _ensure_scope():
            return False
        _status_cache.update(ts=time.time(), logged=ok)
    return ok

def _fetch_self(client):

    r = client.s.get(f"{BASE}/auth/user", timeout=20)

    if r.status_code != 200:

        return None

    u = r.json()
    if not isinstance(u, dict) or not u.get('id') or u.get('requiresTwoFactorAuth'):
        return None

    # /auth/user 的 state/location 是"自己看自己"的陈旧视图（在线也报 offline 的已知怪癖）；
    

    try:

        ur = client.s.get(f"{BASE}/users/{u.get('id')}", timeout=20)

        if ur.status_code == 200:

            u2 = ur.json()

            for k in ("state", "location", "status", "statusDescription",

                      "currentAvatarThumbnailImageUrl", "currentAvatar", "last_login",
                      "username", "date_joined", "twoFactorAuthEnabled"):

                if u2.get(k):

                    u[k] = u2[k]

    except requests.RequestException:

        pass

    t = trust_rank(u.get("tags"))

    data = {"id": u.get("id"), "name": u.get("displayName"),

            "thumb": u.get("currentAvatarThumbnailImageUrl") or "",

            "avatar_id": u.get("currentAvatar"),

            "state": u.get("state") or "offline",

            "location": u.get("location") or "",

            "status": u.get("status") or "", "desc": u.get("statusDescription") or "",

            "trust": {"name": t[0], "color": t[1]}}

    data.update(username=u.get("username"), date_joined=u.get("date_joined"),
                last_login=u.get("last_login"), twoFA=u.get("twoFactorAuthEnabled"))

    return data

def _refresh_self(client, epoch):
    def work():
        data = _fetch_self(client)
        with _SESSION_SCOPE.lock:
            if _ensure_scope() != epoch:
                return None
            _self_cache.update(ts=time.time(), data=deepcopy(data))
        return data
    return _FLIGHTS.run((epoch, "self"), work)


def get_self(client, force=False):
    epoch = _client_epoch(client)
    if epoch is None:
        return None
    with _SESSION_SCOPE.lock:
        data, age = deepcopy(_self_cache["data"]), time.time() - _self_cache["ts"]
    if not force and data and age < 120:
        return data
    if not force and data and age < 600:
        _REFRESHER.submit((epoch, "self"), lambda: _refresh_self(client, epoch))
        data["stale"] = True
        return data
    return deepcopy(_refresh_self(client, epoch))


def fetch_world(client, wid):

    """世界详情（内存缓存 1 小时）"""

    if not wid or not wid.startswith("wrld_"):

        return None

    epoch = _client_epoch(client)
    if epoch is None:
        return None
    with _SESSION_SCOPE.lock:
        hit = _world_cache.get(wid)
        if hit and time.time() - hit[0] < 3600:
            return deepcopy(hit[1])

    try:

        r = client.s.get(f"{BASE}/worlds/{wid}", timeout=8)

        if r.status_code != 200:

            return None

        w = r.json()

    except requests.RequestException:

        return None

    out = {"id": wid, "name": w.get("name"), "author": w.get("authorName"),

           "capacity": w.get("capacity"), "recommended_capacity": w.get("recommendedCapacity"),

           "visits": w.get("visits"), "favorites": w.get("favorites"),

           "heat": w.get("heat"), "population": w.get("population"),

           "thumb": w.get("thumbnailImageUrl") or w.get("imageUrl") or "",
           "image": w.get("imageUrl") or w.get("thumbnailImageUrl") or "",
           "platforms": sorted({x.get("platform") for x in w.get("unityPackages", []) if x.get("platform")}),
           "org": w.get("organization"),

           "publication": w.get("publicationDate"), "updated": w.get("updated_at"),

           "created": w.get("created_at"),

           "description": w.get("description") or "", "tags": w.get("tags") or [],

           "instances": w.get("instances") or [], "raw": w}

    with _SESSION_SCOPE.lock:
        if epoch != _ensure_scope():
            return None
        _world_cache[wid] = (time.time(), deepcopy(out))
        from services.worlds import save_world
        save_world(DB_PATH, (_self_cache.get('data') or {}).get('id'), wid, time.time(), out)
        while len(_world_cache)>512:
            _world_cache.pop(next(iter(_world_cache)))
    return out

def api_status():

    cfg = load_config()

    conn = db_ro()

    try:

        row = conn.execute("SELECT value FROM meta WHERE key='last_sync'").fetchone()

        last_sync = int(row[0]) if row else None

        online_count = conn.execute("SELECT count(*) FROM friends_current").fetchone()[0]

        all_count = conn.execute("SELECT count(*) FROM friends_all").fetchone()[0]

        web_count = conn.execute(

            "SELECT count(*) FROM friends_current WHERE state='active'").fetchone()[0]

        row2 = conn.execute("SELECT value FROM meta WHERE key='watch_source'").fetchone()

    finally:

        conn.close()

    try:

        watch_source = json.loads(row2[0]) if row2 else None

    except ValueError:

        watch_source = None

    bark = cfg.get("bark", {})

    bark_key = (bark.get("key") or "").strip()

    return {

        "logged_in": check_logged(cfg),

        "last_sync": last_sync, "now": int(time.time()),

        "poll_seconds": cfg.get("poll_seconds", 30),

        "online_count": online_count, "all_count": all_count,

        "web_count": web_count,

        "watch_source": watch_source,

        "bark_configured": bool(bark.get("enabled")) and bool(bark_key) and not bark_key.startswith("把你的"),

        "telegram_enabled": bool(cfg.get("telegram", {}).get("enabled")),

    }

def api_self():

    epoch = _ensure_scope()
    client = VRChatClient(load_config())

    # 不强刷：120s 缓存内复用（权威在场合并已让一次状态 = 两个请求）；
    # 登录/改状态路径会主动清 _self_cache 保证即时性

    s = get_self(client)

    if not s:

        return {"logged_in": False, "error": "登录已过期，请重新登录"}

    loc = s["location"]

    wid, _iid, label = parse_location(loc)

    world = fetch_world(client, wid) if wid else None

    s["world"] = (world or {}).get("name") or wid or None

    s["instance_label"] = label

    s["logged_in"] = True

    # 账号页的详细字段（10 分钟缓存：loadSelf 每 5s 调用本接口，不能每次多打 VRChat）

    d = _acct_details(client, s["id"])

    s.update(d)

    try:

        conn = db_ro()

        try:

            s["friends_count"] = conn.execute("SELECT COUNT(*) c FROM friends_all").fetchone()["c"]

        finally:

            conn.close()

    except sqlite3.Error:

        s["friends_count"] = None

    try:

        with open(AUTH_PATH, "r", encoding="utf-8") as f:

            s["credentials_saved"] = bool(json.load(f).get("credentials"))

    except (OSError, ValueError):

        s["credentials_saved"] = False

    if epoch != _ensure_scope():
        return {"logged_in": False, "error": "账号会话已变更，请刷新"}
    return s

_ACCT_CACHE = {"ts": 0, "data": {}}

def _acct_details(client, uid):
    epoch = _client_epoch(client)
    if epoch is None:
        return {}
    with _SESSION_SCOPE.lock:
        cached = _self_cache["data"] or {}
        if cached.get("id") == uid:
            return {k: cached.get(k) for k in ("username", "date_joined", "last_login", "twoFA")}
        if (_ACCT_CACHE.get("uid") == uid and _ACCT_CACHE["data"]
                and time.time() - _ACCT_CACHE["ts"] < 600):
            return deepcopy(_ACCT_CACHE["data"])
    try:
        r = client.s.get(f"{BASE}/users/{uid}", timeout=20)
        if r.status_code != 200:
            return {}
        u = r.json()
        data = {"username": u.get("username"), "date_joined": u.get("date_joined"),
                "last_login": u.get("last_login"), "twoFA": u.get("twoFactorAuthEnabled")}
        with _SESSION_SCOPE.lock:
            if _ensure_scope() != epoch:
                return {}
            _ACCT_CACHE.update(ts=time.time(), uid=uid, data=data)
        return deepcopy(data)
    except requests.RequestException:
        return {}

def api_logout():
    """Serialize with login, atomically clear the session and fence all old cache work."""
    with _lock, _UI_SESSION_LOCK:
        client = _ui_client()
        client.s.cookies.clear()
        client.creds = None
        try:
            client._save_cookies(UI_AUTH_PATH)
        except OSError:
            return {"ok": False, "error": "会话存储写入失败，未能完成登出"}
        _login_ctx.clear()
        _invalidate_session()
    return {"ok": True, "message": "已登出"}

def api_ui_version():

    # 同源原则：返回"当前渲染 HTML 注入的版本"——与页面内标记恒等，
    # 只有重启/重渲染后才可能不同（触发一次 reload）。绝不用另一套哈希来源，
    

    return {"v": _RENDERED_VER or UI_BUILD}

def _access_password(cfg):
    path = os.environ.get("VRCX_PI_ACCESS_TOKEN_FILE")
    if path:
        password = Path(path).read_text(encoding="utf-8").strip()
        if not password:
            raise ValueError("empty managed access token")
        return password
    return (cfg.get("web_password") or "").strip()


def _peer_headers():
    cfg = load_config()
    password = _access_password(cfg)
    if not password:
        return {}
    peer = urlparse(cfg.get("peer_url") or "")
    if peer.scheme != "http" or peer.hostname not in ("127.0.0.1", "::1", "localhost") or peer.username or peer.password:
        raise ValueError("authenticated peer must be loopback")
    return {"X-Web-Token": password}


def api_peer_self():

    """对端实例的账号状态（服务端转发 localhost，浏览器零跨域；只读，会话与对端隔离）"""

    peer = (load_config().get("peer_url") or "").rstrip("/")

    if not peer:

        return {"peer_configured": False}

    try:

        r = requests.get(peer + "/api/self", timeout=15, headers=_peer_headers())

        if r.status_code == 200:

            return {"peer_configured": True, "peer": r.json()}

        return {"peer_configured": True, "peer_error": f"HTTP {r.status_code}"}

    except requests.RequestException as e:

        return {"peer_configured": True, "peer_error": str(e)}

def api_push_config():

    """推送范围配置：mode = all（全部好友）/ favorites（收藏夹，旧行为）/ custom（自选 ID 列表）。

    监控每轮热读 config，保存后下一轮即生效；watch_list 支持 ID（watched() 有 fid 匹配）。"""

    cfg = load_config()

    wl = [str(x) for x in (cfg.get("watch_list") or [])]

    fav = bool(cfg.get("watch_favorites", True))

    push_on = cfg.get("push_enabled", True)

    mode = "off" if push_on is False else ("favorites" if fav else ("custom" if wl else "all"))

    friends = []

    try:

        conn = db_ro()

        try:

            for r in conn.execute("SELECT friend_id, display_name, thumb FROM friends_all ORDER BY display_name"):

                friends.append({"id": r["friend_id"], "name": r["display_name"], "thumb": r["thumb"] or ""})

        finally:

            conn.close()

    except sqlite3.Error:

        pass

    byid = {f["id"]: f for f in friends}

    watch = [byid.get(x) or {"id": x, "name": x, "thumb": ""} for x in wl]

    return {"mode": mode, "watch": watch, "friends": friends}

def api_push_config_set(body):

    mode = body.get("mode")

    ids = [str(x) for x in (body.get("watch_list") or [])]

    if mode not in ("all", "favorites", "custom", "off"):

        return {"ok": False, "error": "无效模式"}

    if mode == "custom" and not ids:

        return {"ok": False, "error": "自选模式至少添加一个好友；要停止推送请选「关闭」"}

    cfg = load_config()

    # push_enabled 总闸：off 关闭全部推送；其余模式一律开启

    cfg["push_enabled"] = (mode != "off")

    if mode == "all":

        cfg["watch_favorites"] = False

        cfg["watch_list"] = []

    elif mode == "favorites":

        cfg["watch_favorites"] = True

        cfg["watch_list"] = []

    elif mode == "custom":

        cfg["watch_favorites"] = False

        cfg["watch_list"] = ids

    try:

        with open(CONFIG_PATH, "w", encoding="utf-8") as f:

            json.dump(cfg, f, ensure_ascii=False, indent=1)

    except OSError as e:

        return {"ok": False, "error": f"写入配置失败: {e}"}

    return {"ok": True, "mode": mode}

def _peer_post(path, payload, timeout=60):

    """向对端实例转发 POST（登录/登出）。凭据仅在 Pi 内部 localhost 传递，不落盘不进日志。"""

    peer = (load_config().get("peer_url") or "").rstrip("/")

    if not peer:

        return {"ok": False, "error": "未配置对端实例（peer_url）"}

    try:

        r = requests.post(peer + path, json=payload, timeout=timeout, headers=_peer_headers())

        if r.status_code == 200:

            return r.json()

        return {"ok": False, "error": f"对端 HTTP {r.status_code}"}

    except requests.RequestException as e:

        return {"ok": False, "error": f"对端不可达: {e}"}

def api_peer_get(path):

    """对端实例 GET 数据转发（双号总览页用；浏览器零跨域）"""

    peer = (load_config().get("peer_url") or "").rstrip("/")

    if not peer:

        return {"peer_configured": False}

    try:

        r = requests.get(peer + path, timeout=15, headers=_peer_headers())

        if r.status_code == 200:

            return {"peer_configured": True, "data": r.json()}

        return {"peer_configured": True, "peer_error": f"HTTP {r.status_code}"}

    except requests.RequestException as e:

        return {"peer_configured": True, "peer_error": str(e)}

def _peer_relay(path, method="GET"):
    peer = (load_config().get("peer_url") or "").rstrip("/")
    return relay_url(peer, path, method, ApiRouter(globals()).allowed(method))

def api_peer_relay_get(path):

    p = _peer_relay(path)

    if isinstance(p, dict):

        return p

    try:

        r = requests.get(p, timeout=10, headers=_peer_headers())

        value = r.json() if r.status_code == 200 else {"error": f"对端 HTTP {r.status_code}"}
        if urlparse(path).path == '/api/image' and isinstance(value, dict) and MEDIA_PATH.fullmatch(value.get('src') or ''):
            value['src'] = '/media/peer/' + value['src'][len('/media/'):]
        return value

    except (requests.RequestException, ValueError) as e:

        return {"error": f"对端不可达: {e}"}

def api_peer_relay_post(path, body):

    p = _peer_relay(path, "POST")

    if isinstance(p, dict):

        return p

    try:

        r = requests.post(p, json=body, timeout=60, headers=_peer_headers())

        return r.json() if r.status_code == 200 else {"error": f"对端 HTTP {r.status_code}"}

    except (requests.RequestException, ValueError) as e:

        return {"error": f"对端不可达: {e}"}

def api_peer_login(body):

    """把登录请求原样转发给对端（对端自己的 _login_ctx 两步验证流程不受影响）"""

    return _peer_post("/api/login", body)

def api_peer_logout():

    return _peer_post("/api/logout", {})

def api_set_status(body):

    status = (body.get("status") or "").strip()

    desc = (body.get("desc") or "").strip()

    client = VRChatClient(load_config())

    s = get_self(client)

    if not s:

        return {"ok": False, "error": "登录已过期"}

    payload = {}

    if status:

        payload["status"] = status

    if "desc" in body:

        payload["statusDescription"] = desc[:32]

    try:

        r = client.s.put(f"{BASE}/users/{s['id']}", json=payload, timeout=20)

    except requests.RequestException as e:

        return {"ok": False, "error": f"网络错误: {e}"}

    if r.status_code != 200:

        return {"ok": False, "error": f"HTTP {r.status_code}"}

    _self_cache["ts"] = 0

    return {"ok": True}

def api_friends():

    conn = db_ro()

    try:

        cur_rows = {r["friend_id"]: dict(r) for r in conn.execute("SELECT * FROM friends_current")}

        all_rows = [dict(r) for r in conn.execute(
            "SELECT * FROM friends_all WHERE in_roster=1 ORDER BY display_name")]

        last_seen = {r["friend_id"]: r["m"] for r in conn.execute(

            "SELECT friend_id, MAX(ts) m FROM events WHERE event='offline' GROUP BY friend_id")}

        last_world = {}

        for r in conn.execute("SELECT friend_id, world_name FROM events "

                              "WHERE event='offline' AND world_name IS NOT NULL "

                              "ORDER BY ts DESC LIMIT 400"):

            if r["friend_id"] not in last_world:

                last_world[r["friend_id"]] = r["world_name"]

    finally:

        conn.close()

    out = []

    for f in all_rows:

        c = cur_rows.get(f["friend_id"])

        loc = (c or {}).get("location") or ""

        wid, _iid, label = parse_location(loc)

        state = (c or {}).get("state") or (

            "online" if loc.startswith("wrld_") else "active") if c else "offline"

        trust = trust_rank(f.get("tags"))

        lg = set()

        try:

            for t in json.loads(f.get("tags") or "[]"):

                if t.startswith("language_"):

                    lg.add(t.split("language_", 1)[1])

        except ValueError:

            pass

        out.append({

            "id": f["friend_id"], "name": f["display_name"],

            "thumb": f.get("thumb") or "",

            "languages": sorted(lg),

            "last_activity": f.get("last_activity"),

            "trust": {"name": trust[0], "color": trust[1]},

            "online": bool(c),

            "web_online": state == "active",

            "state": state,

            "world": ((c or {}).get("world_name")) or wid,

            "world_id": wid, "instance_label": label,

            "location": loc,

            "status": (c or {}).get("status"),

            "desc": (c or {}).get("status_description"),

            "platform": (c or {}).get("platform") or f.get("last_platform"),

            "online_since": (c or {}).get("online_since"),

            "last_seen": last_seen.get(f["friend_id"]),

            "last_world": last_world.get(f["friend_id"]),

            "last_login": f.get("last_login"),

        })

    out.sort(key=lambda x: (not x["online"], (x["name"] or "").lower()))

    return {"friends": out}

def api_feed(limit=500):
    return FeedRepository(DB_PATH, parse_location).read(limit=limit)


def api_history(qs):
    name = (qs.get("name") or [""])[0].strip()
    event_type = (qs.get("type") or [""])[0].strip()
    friend_id = (qs.get("friend_id") or [""])[0].strip()
    try:
        days = max(1, min(int((qs.get("days") or ["3"])[0]), 365))
    except (TypeError, ValueError):
        days = 3
    return FeedRepository(DB_PATH, parse_location).read(
        since=int(time.time()) - days * 86400, name=name,
        event_type=event_type, friend_id=friend_id)

def api_stats(qs):

    """VRCX Charts: 好友时长排行 / 世界热度 / 时段热力图 / 每日在线时长"""

    try:

        days = int((qs.get("days") or ["7"])[0])

    except ValueError:

        days = 7

    days = min(max(days, 1), 90)

    now = int(time.time())

    since = now - days * 86400

    conn = db_ro()

    try:

        game_only = _game_session_filter(conn)

        rows = conn.execute(

            "SELECT display_name, COUNT(*) n, "

            "SUM(MAX(0, MIN(ts, :now) - MAX(ts - duration, :since))) sec "

            "FROM events WHERE event='offline' AND " + game_only + " AND duration IS NOT NULL "

            "AND ts >= :since AND ts - duration <= :now "

            "GROUP BY display_name", {"now": now, "since": since}).fetchall()

        hours = {r["display_name"]: [r["sec"] or 0, r["n"]] for r in rows}

        for r in conn.execute("SELECT display_name, online_since FROM friends_current WHERE state='online'"):

            sec = now - max(r["online_since"], since)

            if sec > 0:

                h = hours.get(r["display_name"], [0, 0])

                h[0] += sec

                hours[r["display_name"]] = h

        # 网页在线时长：active 事件起 → 下一个 online/offline 事件止

        active_secs = {}

        cur_fid, cur_name, act_start = None, None, None

        for r in conn.execute(

                "SELECT friend_id, display_name, event, ts FROM events "

                "WHERE event IN ('active','online','offline') AND ts >= ? "

                "ORDER BY friend_id, ts", (since,)):

            if r["friend_id"] != cur_fid:

                if cur_fid is not None and act_start is not None:

                    active_secs[cur_name] = active_secs.get(cur_name, 0) + (now - max(act_start, since))

                cur_fid, cur_name, act_start = r["friend_id"], r["display_name"], None

            if r["event"] == "active":

                if act_start is None:

                    act_start = r["ts"]

            elif act_start is not None:

                active_secs[cur_name] = active_secs.get(cur_name, 0) + \
                    (min(r["ts"], now) - max(act_start, since))

                act_start = None

        if cur_fid is not None and act_start is not None:

            active_secs[cur_name] = active_secs.get(cur_name, 0) + (now - max(act_start, since))

        friends = sorted(({"name": k, "hours": round(v[0] / 3600, 1), "sessions": v[1],

                           "active_hours": round(active_secs.get(k, 0) / 3600, 1)}

                          for k, v in hours.items()), key=lambda x: -x["hours"])[:15]

        worlds = [{"name": r["world_name"], "visits": r["c"]} for r in conn.execute(

            "SELECT world_name, COUNT(*) c FROM events WHERE event IN ('online','location') "

            "AND ts >= ? AND world_name IS NOT NULL GROUP BY world_name "

            "ORDER BY c DESC LIMIT 10", (since,))]

        heatmap = [[r["d"], r["h"], r["c"]] for r in conn.execute(

            "SELECT CAST(strftime('%w', ts, 'unixepoch', 'localtime') AS INT) d, "

            "CAST(strftime('%H', ts, 'unixepoch', 'localtime') AS INT) h, COUNT(*) c "

            "FROM events WHERE event='online' AND ts >= ? GROUP BY d, h", (since,))]

        # 每日在线总时长 + 每日上线次数：所有会话（含进行中）统一按天拆分

        finished = [dict(r) for r in conn.execute(
            "SELECT id,friend_id,event,ts,duration,prev_state FROM events WHERE event='offline' AND " + game_only + " AND duration IS NOT NULL AND ts >= ?", (since,))]
        project_session_durations(conn, finished)
        sessions = [(r['ts'], r['ts'] - r['session_duration']) for r in finished if r['session_duration'] is not None]

        for r in conn.execute("SELECT online_since FROM friends_current WHERE state='online'"):

            sessions.append((now, max(r["online_since"], since)))

        logins = {r["d"]: r["c"] for r in conn.execute(

            "SELECT date(ts,'unixepoch','localtime') d, COUNT(*) c FROM events "

            "WHERE event='online' AND ts >= ? GROUP BY d", (since,))}

    finally:

        conn.close()

    daily = {}

    for end, start in sessions:

        cur = max(start, since)

        while cur < end:

            d = time.strftime("%Y-%m-%d", time.localtime(cur))

            day_end = int(time.mktime(time.strptime(d, "%Y-%m-%d"))) + 86400

            daily[d] = daily.get(d, 0) + (min(end, day_end) - cur)

            cur = day_end

    daily_list = [{"date": d, "hours": round(v / 3600, 2),

                   "logins": logins.get(d, 0)}

                  for d, v in sorted(daily.items())]

    hmax = max((x[2] for x in heatmap), default=0)

    return {"days": days, "since": since, "friends": friends, "worlds": worlds,

            "heatmap": heatmap, "heatmap_max": hmax, "daily": daily_list}

def api_search(qs):

    """用户搜索（VRCX Search），支持 usr_ 直查"""

    q = ((qs.get("q") or [""])[0] or "").strip()

    if not q:

        return {"users": []}

    cfg = load_config()

    client = VRChatClient(cfg)

    try:

        if q.startswith("usr_"):

            r = client.s.get(f"{BASE}/users/{q}", timeout=20)

            items = [r.json()] if r.status_code == 200 else []

        else:

            r = client.s.get(f"{BASE}/users", params={"search": q, "n": "12"}, timeout=25)

            items = r.json() if r.status_code == 200 else []

    except requests.RequestException as e:

        return {"users": [], "error": f"网络错误: {e}"}

    out = []

    for u in items:

        t = trust_rank(u.get("tags"))

        out.append({

            "id": u.get("id"), "name": u.get("displayName"),

            "thumb": u.get("currentAvatarThumbnailImageUrl") or u.get("userIcon") or "",

            "trust": {"name": t[0], "color": t[1]},

            "state": u.get("state") or "offline",

            "desc": u.get("statusDescription") or "",

        })

    return {"users": out}

def api_world_search(qs):

    """世界搜索（VRCX Search 的世界部分）"""

    q = ((qs.get("q") or [""])[0] or "").strip()

    if not q:

        return {"worlds": []}

    client = VRChatClient(load_config())

    try:

        if q.startswith("wrld_"):

            w = fetch_world(client, q)

            items = [w] if w else []

        else:

            r = client.s.get(f"{BASE}/worlds", params={"search": q, "n": "12",

                                                       "sort": "favorites"}, timeout=25)

            raw = r.json() if r.status_code == 200 else []

            items = []

            for w in raw:

                t = trust_rank(w.get("tags"))  # 复用 tag 解析无意义，世界直接展示

                items.append({"id": w.get("id"), "name": w.get("name"),

                              "author": w.get("authorName"),

                              "thumb": w.get("thumbnailImageUrl") or "",

                              "visits": w.get("visits"), "capacity": w.get("capacity")})

    except requests.RequestException as e:

        return {"worlds": [], "error": f"网络错误: {e}"}

    return {"worlds": items}

def api_random_world():

    client = VRChatClient(load_config())

    for sort in ("random", "shuffle", "heat"):

        try:

            r = client.s.get(f"{BASE}/worlds", params={"sort": sort, "n": "12"}, timeout=25)

            raw = r.json() if r.status_code == 200 else []

            if raw:

                import random as _rnd

                w = _rnd.choice(raw)

                w.pop("description", None)

                w.pop("tags", None)

                return {"world": {"id": w.get("id"), "name": w.get("name"),

                                  "author": w.get("authorName"),

                                  "thumb": w.get("thumbnailImageUrl") or "",

                                  "visits": w.get("visits"), "capacity": w.get("capacity")}}

        except requests.RequestException:

            continue

    return {"world": None, "error": "获取随机世界失败"}

def _world_snapshot(wid):
    """Never waits for remote requests; snapshots are isolated by login generation."""
    _ensure_scope()
    with _SESSION_SCOPE.lock:
        cached = _world_cache.get(wid)
        if cached:
            return deepcopy(cached[1]), time.time() - cached[0] >= 3600
        from services.worlds import cached_world
        cached = cached_world(DB_PATH, (_self_cache.get('data') or {}).get('id'), wid)
        if cached:
            _world_cache[wid] = cached
            while len(_world_cache)>512: _world_cache.pop(next(iter(_world_cache)))
            return deepcopy(cached[1]), time.time()-cached[0]>=3600
    conn = db_ro()
    try:
        row = conn.execute("SELECT name FROM worlds WHERE world_id=?", (wid,)).fetchone()
    finally:
        conn.close()
    return {"id": wid, "name": row[0] if row else wid, "thumb": "", "raw": {}, "instances": []}, True


def api_world(qs):
    from services.worlds import rooms_for_world
    wid = (qs.get("id") or [""])[0].strip()
    if not re.fullmatch(r"wrld_[A-Za-z0-9-]+", wid):
        return {"error": "无效的世界 id"}
    epoch = _ensure_scope()
    world, stale = _world_snapshot(wid)
    conn = db_ro()
    try:
        friends = [dict(r) for r in conn.execute(
            "SELECT display_name,location FROM friends_current WHERE location LIKE ?", (wid+":%",))]
        note = conn.execute("SELECT note FROM world_notes WHERE world_id=?", (wid,)).fetchone()
        visits, last = conn.execute("SELECT COUNT(*),MAX(ts) FROM events WHERE event IN ('online','location') AND location LIKE ?", (wid+":%",)).fetchone()
    finally:
        conn.close()
    if stale:
        _REFRESHER.submit((epoch, "world", wid), lambda: fetch_world(VRChatClient(load_config()), wid) if epoch == _ensure_scope() else None)
    rooms = rooms_for_world(world, friends, parse_location)
    # No peer calls, instance fan-out or creator lookups in the world read path.
    # Detailed occupancy is loaded only for the instance which the user opens.
    return {"world": world, "instances": rooms, "stale": stale,
            "pub_online": world.get("publicOccupants", world.get("raw", {}).get("publicOccupants")),
            "priv_online": world.get("raw", {}).get("privateOccupants"),
            "visits_local": visits, "last_visit": last, "note": note[0] if note else ""}


def api_world_note(body):

    wid = (body.get("id") or "").strip()

    note = body.get("note") or ""

    if not wid.startswith("wrld_"):

        return {"ok": False, "error": "无效的世界 id"}

    conn = sqlite3.connect(DB_PATH)

    try:

        conn.execute("INSERT OR REPLACE INTO world_notes VALUES (?,?,?)",

                     (wid, note, int(time.time())))

        conn.commit()

    finally:

        conn.close()

    return {"ok": True}

_instance_cache = {}

def api_instance(qs):
    loc = ((qs.get("location") or [""])[0] or "").strip()
    if not re.fullmatch(r"wrld_[A-Za-z0-9-]+:[^/\\?#\s]+", loc):
        return {"error": "格式应为 wrld_xxx:实例编号"}
    epoch = _ensure_scope()
    wid, iid = loc.split(":", 1)  # Keep the complete access/region/nonce suffix.
    world, _ = _world_snapshot(wid)
    conn = db_ro()
    try:
        friends = [dict(r) for r in conn.execute(
            "SELECT friend_id AS id,display_name AS name FROM friends_current WHERE location=?", (loc,))]
    finally:
        conn.close()
    with _SESSION_SCOPE.lock:
        cached = _instance_cache.get(loc)
        live = deepcopy(cached[1]) if cached else None
    stale = not cached or time.time() - cached[0] > 15
    if stale:
        def refresh():
            if epoch != _ensure_scope(): return
            client = VRChatClient(load_config())
            try:
                response = client.s.get(f"{BASE}/instances/{loc}", timeout=8)
                if response.status_code != 200: return
                value = response.json()
                result = {"user_count": value.get("userCount"), "capacity": value.get("capacity"),
                          "queue_size": value.get("queueSize"), "secure_name": value.get("secureName"),
                          "creator_id": value.get("ownerId") or value.get("creatorId")}
                with _SESSION_SCOPE.lock:
                    if epoch == _ensure_scope():
                        _instance_cache[loc] = (time.time(), result)
                        while len(_instance_cache) > 256: _instance_cache.pop(next(iter(_instance_cache)))
            except requests.RequestException:
                pass
        _REFRESHER.submit((epoch,"instance",loc), refresh)
    if live is not None: live["friends_in"] = friends
    return {"world": world, "instance_id": iid, "location": loc,
            "label": parse_location(loc)[2], "live": live, "friends_in": friends, "stale": stale}

def api_favorites():

    """VRCX Favorites: 好友/世界/头像收藏"""

    client = VRChatClient(load_config())

    out = {"friends": [], "worlds": [], "avatars": [], "error": None}

    conn = db_ro()

    try:

        name_map = {r["friend_id"]: r["display_name"] for r in

                    conn.execute("SELECT friend_id, display_name FROM friends_all")}

        cur_ids = {r["friend_id"] for r in conn.execute("SELECT friend_id FROM friends_current")}

    finally:

        conn.close()

    def fav_ids(t):

        try:

            r = client.s.get(f"{BASE}/favorites", params={"type": t, "n": "100"}, timeout=20)

            if r.status_code != 200:

                return []

            return [f.get("favoriteId") for f in r.json() if f.get("type") == t and f.get("favoriteId")]

        except requests.RequestException:

            return []

    for uid in fav_ids("friend"):

        nm = name_map.get(uid, uid)

        out["friends"].append({"id": uid, "name": nm, "online": uid in cur_ids})

    for wid in fav_ids("world")[:12]:

        w = fetch_world(client, wid)

        if w:

            out["worlds"].append({"id": wid, "name": w["name"], "thumb": w["thumb"],

                                  "author": w["author"], "visits": w["visits"]})

        else:

            out["worlds"].append({"id": wid, "name": wid, "thumb": "", "author": "", "visits": None})

    try:

        r = client.s.get(f"{BASE}/avatars/favorites", params={"n": "24"}, timeout=20)

        if r.status_code == 200:

            for a in r.json():

                out["avatars"].append({"id": a.get("id"), "name": a.get("name"),

                                       "image": a.get("imageUrl") or "",

                                       "author": a.get("authorName")})

    except requests.RequestException:

        pass

    if not out["avatars"]:

        aids = fav_ids("avatar")[:12]

        for aid in aids:

            try:

                r = client.s.get(f"{BASE}/avatars/{aid}", timeout=15)

                if r.status_code == 200:

                    a = r.json()

                    out["avatars"].append({"id": aid, "name": a.get("name"),

                                           "image": a.get("imageUrl") or "",

                                           "author": a.get("authorName")})

            except requests.RequestException:

                continue

    return out

def api_notifications():

    """VRCX Notifications: VRChat 官方通知列表（好友请求/邀请等）"""

    client = VRChatClient(load_config())

    try:

        r = client.s.get(f"{BASE}/auth/user/notifications", timeout=20)

        if r.status_code != 200:

            return {"items": [], "error": f"HTTP {r.status_code}"}

        items = []

        for n in r.json():

            grp = n.get("groupName") or ""

            if not grp and isinstance(n.get("group"), dict):

                grp = (n.get("group") or {}).get("name") or ""

            items.append({"id": n.get("id"), "type": n.get("type"),

                          "message": n.get("message") or "",

                          "sender": n.get("senderUsername") or "",

                          "sender_id": n.get("senderUserId") or "",

                          "group": grp,

                          "imageUrl": n.get("imageUrl") or n.get("thumbnailImageUrl") or "",

                          "created": n.get("created"),

                          "seen": n.get("seen", False)})

        return {"items": items}

    except requests.RequestException as e:

        return {"items": [], "error": f"网络错误: {e}"}

def api_avatars():

    """VRCX MyAvatars: 正在穿着 / 自己上传的 / 收藏可切换的"""

    client = VRChatClient(load_config())

    s = get_self(client)

    if not s:

        return {"own": [], "current": None, "favorites": [], "error": "登录已过期"}

    def pack(a):

        return {"id": a.get("id"), "name": a.get("name"),

                "image": a.get("imageUrl") or "",

                "thumb": a.get("thumbnailImageUrl") or "",

                "author": a.get("authorName") or "",

                "release": a.get("releaseStatus") or ""}

    own = []

    try:

        r = client.s.get(f"{BASE}/avatars", params={"n": "96", "releaseStatus": "all"},

                         timeout=25)

        if r.status_code == 200:

            own = [pack(a) for a in r.json()]

    except requests.RequestException:

        pass

    current = None

    aid = s.get("avatar_id") or ""

    if aid.startswith("avtr_"):

        try:

            r = client.s.get(f"{BASE}/avatars/{aid}", timeout=20)

            if r.status_code == 200:

                current = pack(r.json())

                current["own"] = r.json().get("authorId") == s["id"]

        except requests.RequestException:

            pass

    favorites = []

    try:

        r = client.s.get(f"{BASE}/avatars/favorites", params={"n": "48"}, timeout=20)

        if r.status_code == 200:

            favorites = [pack(a) for a in r.json()]

    except requests.RequestException:

        pass

    if not favorites:

        try:

            r = client.s.get(f"{BASE}/favorites", params={"type": "avatar", "n": "24"},

                             timeout=20)

            ids = [f.get("favoriteId") for f in r.json()

                   if f.get("type") == "avatar" and f.get("favoriteId")] if r.status_code == 200 else []

            for i in ids[:12]:

                rr = client.s.get(f"{BASE}/avatars/{i}", timeout=15)

                if rr.status_code == 200:

                    favorites.append(pack(rr.json()))

        except requests.RequestException:

            pass

    return {"own": own, "current": current, "favorites": favorites}

def api_avatar(aid):

    aid = (aid or "").strip()

    if not aid.startswith("avtr_"):

        return {"error": "无效的模型 id"}

    client = VRChatClient(load_config())

    try:

        r = client.s.get(f"{BASE}/avatars/{aid}", timeout=20)

    except requests.RequestException as e:

        return {"error": f"网络错误: {e}"}

    if r.status_code == 401:

        return {"error": "登录已过期，请重新登录"}

    if r.status_code != 200:

        return {"error": f"获取模型信息失败 HTTP {r.status_code}"}

    a = r.json()

    return {"avatar": {

        "id": a.get("id"), "name": a.get("name"), "author": a.get("authorName"),

        "image": a.get("imageUrl") or "", "thumb": a.get("thumbnailImageUrl") or "",

        "release": a.get("releaseStatus") or "", "version": a.get("version"),

        "platform": a.get("platform") or "", "description": a.get("description") or "",

        "created": a.get("created_at"), "updated": a.get("updated_at"), "raw": a}}

def api_avatar_select(body):

    aid = (body.get("id") or "").strip()

    if not aid.startswith("avtr_"):

        return {"ok": False, "error": "无效的头像 id"}

    client = VRChatClient(load_config())

    try:

        r = client.s.put(f"{BASE}/avatars/{aid}/select", timeout=20)

        if r.status_code != 200:

            return {"ok": False, "error": f"HTTP {r.status_code}"}

        _self_cache["ts"] = 0

        return {"ok": True}

    except requests.RequestException as e:

        return {"ok": False, "error": f"网络错误: {e}"}

def api_moderations():

    """VRCX Moderation: 屏蔽/静音列表"""

    client = VRChatClient(load_config())

    try:

        r = client.s.get(f"{BASE}/auth/user/playermoderations", timeout=20)

        if r.status_code != 200:

            return {"items": [], "error": f"HTTP {r.status_code}"}

        items = [{"id": m.get("id"), "type": m.get("type"),

                  "user": m.get("targetDisplayName") or m.get("moderatedUserId"),

                  "user_id": m.get("moderatedUserId"),

                  "created": m.get("created")} for m in r.json()]

        return {"items": items}

    except requests.RequestException as e:

        return {"items": [], "error": f"网络错误: {e}"}

def api_moderate(body):

    """屏蔽/解除屏蔽/静音/解除静音"""

    uid = (body.get("id") or "").strip()

    mtype = (body.get("type") or "").strip()

    if not uid.startswith("usr_") or mtype not in ("block", "unblock", "mute", "unmute"):

        return {"ok": False, "error": "参数无效"}

    epoch = _ensure_scope()
    client = VRChatClient(load_config())

    try:

        removing = mtype in ('unblock', 'unmute')
        path = 'auth/user/unplayermoderate' if removing else 'auth/user/playermoderations'
        send = client.s.put if removing else client.s.post
        r = send(f"{BASE}/{path}",
                 json={"moderated": uid, "type": mtype[2:] if removing else mtype}, timeout=20)

        if r.status_code not in (200, 201):

            return {"ok": False, "error": f"HTTP {r.status_code}"}

        field='is_blocked' if mtype in ('block','unblock') else 'is_muted'
        _apply_friend_metadata(uid,{field:mtype in ('block','mute')},epoch)
        return {"ok": True}

    except requests.RequestException as e:

        return {"ok": False, "error": f"网络错误: {e}"}

_friend_cache = {}  # uid -> (ts, data)


def _apply_friend_metadata(uid, changes, epoch):
    with _SESSION_SCOPE.lock:
        if epoch == _ensure_scope():
            hit = _friend_cache.get(uid)
            if hit:
                value = deepcopy(hit[1]);value['user'].update(changes)
                value['_metadata_revision'] = value.get('_metadata_revision', 0) + 1
                if 'note' in changes and isinstance(value.get('raw'), dict):
                    value['raw']['note'] = changes['note']
                _friend_cache[uid] = (hit[0], value)
                owner = (_self_cache.get('data') or {}).get('id')
                if owner and value.get('_account_id') == owner:
                    try:
                        with sqlite3.connect(DB_PATH) as conn:
                            conn.execute('UPDATE user_cache SET payload=? WHERE uid=?', (json.dumps(value,ensure_ascii=False),uid))
                    except sqlite3.Error:
                        pass


def _local_presence(payload, uid):
    conn = db_ro()
    try:
        cur = conn.execute("SELECT * FROM friends_current WHERE friend_id=?", (uid,)).fetchone()
        try:
            roster = conn.execute("SELECT in_roster,thumb FROM friends_all WHERE friend_id=?", (uid,)).fetchone()
        except sqlite3.OperationalError:
            roster = None
        last = conn.execute("SELECT world_name,location,ts FROM events WHERE friend_id=? AND location LIKE 'wrld_%:%' AND event IN ('offline','online','location') ORDER BY ts DESC LIMIT 1", (uid,)).fetchone()
    except sqlite3.OperationalError:
        cur, roster, last = None, None, None
    finally:
        conn.close()
    u = payload['user']
    if cur:
        cur = dict(cur)
        u.update(state=cur.get('state') or ('online' if cur.get('location') not in ('', 'offline', None) else 'active'),
                 location=cur.get('location') or '', online_since=cur.get('online_since'),
                 status=cur.get('status'), statusDescription=cur.get('status_description') or cur.get('desc') or '')
    else:
        if roster is not None or not payload.get('profile_loaded'):
            u.update(state='offline',location='',online_since=None)
        else:
            from services.presence import state_of
            u['state'] = state_of(u) if u.get('state') in ('online','active','offline') or u.get('location') else 'unknown'
            u['location'] = u.get('location') or ''
    u['cur_state'] = u['state']
    if roster is not None:
        u['isFriend'] = bool(roster[0])
        u['_avatar_fallback'] = (dict(cur).get('avatar') if cur else '') or roster[1] or ''
    wid, _, label = parse_location(u['location'])
    u.update(world_id=wid, instance_label=label)
    if wid:
        world, _ = _world_snapshot(wid)
        u.update(world=world.get('name'), world_thumb=world.get('thumb') or '')
    else:
        u.update(world={'private':'位于私人房间','traveling':'正在传送'}.get(u['location'],'') , world_thumb='')
    if last:
        payload['last_room'] = {'world':last[0], 'location':last[1], 'ts':last[2]}
    payload['events'] = FeedRepository(DB_PATH, parse_location).read(limit=30, friend_id=uid)['events']
    return payload


def api_friend_section(qs):
    uid = (qs.get('id') or [''])[0]
    part = (qs.get('part') or [''])[0]
    if part not in ('info','groups','worlds','avatars','mutual') or not uid.startswith('usr_'):
        return {'error':'无效的详情分区'}
    epoch = _ensure_scope()
    return _FLIGHTS.run((epoch,'friend-section',uid,part), lambda: _friend_live(uid,part))


def _game_session_filter(conn):
    # A web process may start before the monitor upgrades a legacy database.
    columns = {row[1] for row in conn.execute('PRAGMA table_info(events)')}
    return "COALESCE(prev_state,'online')!='active'" if 'prev_state' in columns else '1=1'


def _friend_local_payload(uid):
    _ensure_scope()
    with _SESSION_SCOPE.lock:
        owner = (_self_cache.get("data") or {}).get("id")

    # 1) 全量镜像优先（VRCX 同款：live 刷新落地，bio/群组/共同好友/原始 JSON 全在）

    try:

        conn0 = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)

        try:

            r0 = conn0.execute("SELECT payload FROM user_cache WHERE uid=?", (uid,)).fetchone()

            if r0:

                out0 = json.loads(r0[0])

                if isinstance(out0, dict) and (out0.get("user") or {}).get('id') == uid and owner and out0.get("_account_id")==owner:

                    out0["stale"] = True

                    return _local_presence(out0, uid)

        finally:

            conn0.close()

    except (sqlite3.Error, ValueError):

        pass

    # 2) 基础组装（无缓存时的兜底）：user 从 friends_all/friends_current 组装，

    # 活动/热力图/最近房间等本来就出自本地 events 库。缺的字段（bio/群组/备注/共同好友/

    # 实时人数）由独立分区请求补齐；简介刷新不等待各标签页或房间网络请求。

    try:

        conn = db_ro()

        try:

            f = conn.execute("SELECT * FROM friends_all WHERE friend_id=?", (uid,)).fetchone()

            if not f:

                return None

            f = dict(f)

            cur = conn.execute("SELECT * FROM friends_current WHERE friend_id=?", (uid,)).fetchone()

            cur = dict(cur) if cur else None

            events = FeedRepository(DB_PATH, parse_location).read(limit=30, friend_id=uid)['events']

            row = conn.execute("SELECT online_since, state FROM friends_current "

                               "WHERE friend_id=?", (uid,)).fetchone()

            online_since = row["online_since"] if row else None

            cur_state = (row["state"] or None) if row else None

            since30 = int(time.time()) - 30 * 86400

            heat = [[x["d"], x["h"], x["c"]] for x in conn.execute(

                "SELECT CAST(strftime('%w', ts, 'unixepoch', 'localtime') AS INT) d, "

                "CAST(strftime('%H', ts, 'unixepoch', 'localtime') AS INT) h, COUNT(*) c "

                "FROM events WHERE friend_id=? AND event='online' AND ts >= ? GROUP BY d, h",

                (uid, since30))]

            logins30 = conn.execute(

                "SELECT COUNT(*) FROM events WHERE friend_id=? AND event='online' AND ts >= ?",

                (uid, since30)).fetchone()[0]

            hours30 = conn.execute(

                "SELECT COALESCE(SUM(MAX(0, MIN(ts, :now) - MAX(ts - duration, :since))), 0) s "

                "FROM events WHERE friend_id=:uid AND event='offline' AND " + _game_session_filter(conn) + " AND duration IS NOT NULL "

                "AND ts >= :since", {"now": int(time.time()), "since": since30, "uid": uid}).fetchone()["s"]

            last_room = None

            rowl = conn.execute(

                "SELECT world_name, location, ts FROM events WHERE friend_id=:uid "

                "AND event='location' ORDER BY ts DESC LIMIT 5", {"uid": uid}).fetchall()

        finally:

            conn.close()

    except sqlite3.Error:

        return None

    loc = (cur or {}).get("location") or ""

    wid, _iid, label = parse_location(loc)

    wname = None

    try:

        conn = db_ro()

        try:

            if wid:

                w = conn.execute("SELECT name FROM worlds WHERE world_id=?", (wid,)).fetchone()

                wname = w["name"] if w else None

        finally:

            conn.close()

    except sqlite3.Error:

        pass

    tags = json.loads(f["tags"]) if f["tags"] else []

    t = trust_rank(tags)

    langs = sorted({x.split("language_", 1)[1] for x in tags if x.startswith("language_")})

    state = ((cur or {}).get("state") or ("online" if loc.startswith("wrld_") else "active")) if cur else "offline"

    user = {"id": uid, "username": f["username"], "displayName": f["display_name"],

            "bio": "", "bioLinks": [], "pronouns": "",

            "status": (cur or {}).get("status") or "", "statusDescription": (cur or {}).get("desc") or "",

            "currentAvatarThumbnailImageUrl": f["thumb"] or "", "currentAvatarImageUrl": "",

            "userIcon": "", "profilePicOverride": "", "bannerColor": "",

            "state": state, "location": loc, "worldId": wid,

            "last_login": f["last_login"], "last_activity": f["last_activity"],

            "last_platform": f["last_platform"],

            "date_joined": None, "isFriend": bool(f.get("in_roster", 1)), "friendRequestStatus": None,

            "allowAvatarCopying": False}

    user["trust"] = {"name": t[0], "color": t[1]}

    user["languages"] = langs

    user["world"] = wname or wid

    user["world_id"] = wid

    user["instance_label"] = label

    user["note"] = ""

    user["is_blocked"] = False

    user["is_muted"] = False

    user["online_since"] = online_since

    user["cur_state"] = cur_state or state

    user["avatar_name"] = ""

    user["representing"] = []

    return _local_presence({"user": user, "events": events, "groups": [],

            "worlds_created": [], "avatars_created": [], "live": None,

            "heat": heat, "logins30": logins30,

            "hours30": round((hours30 or 0) / 3600, 1), "raw": None,

            "last_room": last_room,

            "mutual": {"counts": [], "friends": []},

            "stale": True}, uid)

def api_friend(uid):
    if not uid or not uid.startswith("usr_"):
        return {"error": "无效的用户 id"}
    epoch = _ensure_scope()
    with _SESSION_SCOPE.lock:
        hit = _friend_cache.get(uid)
        if hit and (hit[1].get('user') or {}).get('id') == uid and not hit[1].get("stale") and time.time() - hit[0] < 300:
            return _local_presence(deepcopy(hit[1]), uid)
    local = _friend_local_payload(uid)
    if local is not None:
        with _SESSION_SCOPE.lock:
            if epoch != _ensure_scope():
                return {"error": "账号会话已变更，请刷新"}
            _friend_cache[uid] = (time.time(), local)
        def refresh():
            live = _friend_live(uid)
            with _SESSION_SCOPE.lock:
                if epoch == _ensure_scope() and not live.get("error"):
                    _friend_cache[uid] = (time.time(), live)
                    while len(_friend_cache) > 256:
                        _friend_cache.pop(next(iter(_friend_cache)))
        _REFRESHER.submit((epoch, "friend", uid), refresh)
        return deepcopy(local)
    return _FLIGHTS.run((epoch, "friend", uid), lambda: _friend_live(uid))

def _friend_live(uid, section="profile"):
    """One partition per request, like VRCX's independent dialog resources."""
    if not uid or not uid.startswith("usr_"):
        return {"error": "无效的用户 id"}
    epoch = _ensure_scope()
    with _SESSION_SCOPE.lock:
        owner = (_self_cache.get("data") or {}).get("id")
        previous = deepcopy((_friend_cache.get(uid) or (0, {}))[1])
        if previous and (previous.get('user') or {}).get('id') != uid:
            previous = {}
        metadata_revision = previous.get('_metadata_revision', 0)
    database = DB_PATH
    client = VRChatClient(load_config())
    def read(path, params=None):
        if epoch != _ensure_scope(): raise requests.RequestException("账号会话已变更")
        response = client.s.get(BASE + path, params=params, timeout=10)
        if response.status_code != 200:
            raise requests.RequestException("获取详情失败 HTTP " + str(response.status_code))
        value = response.json()
        if isinstance(value, dict) and value.get('requiresTwoFactorAuth'):
            raise requests.RequestException('登录已过期，请在账号页面重新登录')
        if path == '/users/' + uid and (not isinstance(value, dict) or value.get('id') != uid):
            raise requests.RequestException('用户资料暂不可用，已保留本地镜像')
        return value
    out = previous or _friend_local_payload(uid) or {
        "user": {}, "events": [], "heat": [], "groups": [], "worlds_created": [],
        "avatars_created": [], "mutual": {"counts":{},"friends":[]}, "last_room":None}
    try:
        raw = out.get("raw")
        if section == "profile" or not isinstance(raw, dict) or not raw.get("id"):
            raw = read("/users/" + uid)
            user = deepcopy(out.get('user') or {})
            user.update({key: raw[key] for key in (
                "id", "username", "displayName", "bio", "bioLinks", "pronouns", "status",
                "statusDescription", "currentAvatarThumbnailImageUrl", "currentAvatarImageUrl",
                "userIcon", "profilePicOverride", "bannerColor", "state", "location",
                "last_login", "last_activity", "last_platform", "date_joined", "isFriend",
                "friendRequestStatus", "allowAvatarCopying", "note") if key in raw})
            # Preserve already fetched private metadata when the public profile changes.
            for key in ("note","is_blocked","is_muted"):
                user[key] = out.get("user", {}).get(key)
            trust = trust_rank(raw.get("tags"))
            user.update(trust={"name":trust[0],"color":trust[1]},
                        languages=sorted({t.split("language_",1)[1] for t in raw.get("tags",[]) if t.startswith("language_")}),
                        avatar_name=out.get("user",{}).get("avatar_name"), representing=out.get("user",{}).get("representing"))
            out.update(user=user, raw=raw, profile_loaded=True)
        if section == "info":
            # Pinned VRCX userTransforms consumes the viewer's note from GET
            # users/{id}; misc.saveNote writes POST userNotes. A per-friend
            # /auth/user/friends/{id}/note endpoint does not exist (live 404).
            note = raw.get('note') or ''
            moderations = read("/auth/user/playermoderations")
            kinds = {m.get('type') for m in moderations if m.get('moderatedUserId') == uid}
            out['user'].update(note=note, is_blocked='block' in kinds, is_muted='mute' in kinds)
        elif section == "groups":
            groups = read(f"/users/{uid}/groups")
            out['groups'] = [{"id":g.get('groupId'),"name":g.get('name') or '',
                              "members":g.get('memberCount'),"icon":g.get('iconUrl') or '',
                              "isRepresenting":g.get('isRepresenting',False)} for g in groups[:24]]
            represented = next((g for g in out['groups'] if g['isRepresenting']), None)
            out['user']['representing'] = represented
        elif section in ("worlds","avatars"):
            items = read('/'+section, {"userId":uid,"n":"12"})
            if section == 'worlds':
                out['worlds_created'] = [{"id":w.get('id'),"name":w.get('name') or '',"thumb":w.get('thumbnailImageUrl') or '',"visits":w.get('visits')} for w in items]
            else:
                out['avatars_created'] = [{"id":w.get('id'),"name":w.get('name') or '',"image":w.get('imageUrl') or ''} for w in items]
        elif section == "mutual":
            counts = read(f"/users/{uid}/mutuals")
            items = read(f"/users/{uid}/mutuals/friends", {"n":"100"})
            out['mutual'] = {"counts":counts,"friends":[{"id":f.get('id'),"name":f.get('displayName') or '',"thumb":f.get('iconUrl') or '',"state":f.get('state') or 'offline'} for f in items]}
    except requests.RequestException as error:
        return {"error":str(error)}
    out = _local_presence(out, uid)
    out.update(stale=False, profile_loaded=True,
               loaded_sections=list(set(out.get('loaded_sections', [])) | {section}))
    out['section_times'] = dict(out.get('section_times') or {}, **{section:time.time()})
    with _SESSION_SCOPE.lock:
        if epoch != _ensure_scope(): return {"error":"账号会话已变更，请刷新"}
        # Parallel tab requests own only their partition. A late groups reply
        # cannot replace a newer note, moderation flag or another tab's data.
        latest = deepcopy((_friend_cache.get(uid) or (0, {}))[1])
        if latest.get('profile_loaded'):
            combined = latest
            combined.update({k:v for k,v in out.items() if k not in
                             ('user','raw','groups','worlds_created','avatars_created','mutual','loaded_sections','section_times','_metadata_revision')})
            metadata_changed = latest.get('_metadata_revision', 0) != metadata_revision
            if section == 'profile':
                personal = {k:latest['user'].get(k) for k in ('note','is_blocked','is_muted','representing')}
                combined['user'] = out['user']
                combined['user'].update(personal)
                combined['raw'] = out['raw']
                if metadata_changed:
                    combined['raw']['note'] = personal['note']
            elif section == 'info':
                if not metadata_changed:
                    combined['user'].update({k:out['user'].get(k) for k in ('note','is_blocked','is_muted')})
            elif section == 'groups':
                combined['groups'] = out['groups']
                combined['user']['representing'] = out['user'].get('representing')
            elif section in ('worlds','avatars','mutual'):
                key = {'worlds':'worlds_created','avatars':'avatars_created','mutual':'mutual'}[section]
                combined[key] = out[key]
            combined['loaded_sections'] = sorted(set(latest.get('loaded_sections',[])) | set(out['loaded_sections']))
            combined['section_times'] = dict(latest.get('section_times') or {}, **{section:out['section_times'][section]})
            out = _local_presence(combined, uid)
        if owner:
            out['_account_id'] = owner
            try:
                conn = sqlite3.connect(database)
                try:
                    conn.execute("CREATE TABLE IF NOT EXISTS user_cache (uid TEXT PRIMARY KEY,payload TEXT,ts REAL)")
                    conn.execute("INSERT OR REPLACE INTO user_cache VALUES (?,?,?)", (uid,json.dumps(out,ensure_ascii=False),time.time()))
                    conn.commit()
                finally: conn.close()
            except sqlite3.Error: pass
        _friend_cache[uid] = (time.time(),deepcopy(out))
        while len(_friend_cache)>256: _friend_cache.pop(next(iter(_friend_cache)))
    return deepcopy(out)


def api_friend_note(body):

    uid = (body.get("id") or "").strip()

    note = body.get("note") or ""

    if not uid.startswith("usr_"):

        return {"ok": False, "error": "无效的用户 id"}

    epoch = _ensure_scope()
    client = VRChatClient(load_config())

    try:

        r = client.s.post(f"{BASE}/userNotes",
                          json={"targetUserId": uid, "note": note}, timeout=20)

    except requests.RequestException as e:

        return {"ok": False, "error": f"网络错误: {e}"}

    if r.status_code not in (200, 201):

        return {"ok": False, "error": f"保存失败 HTTP {r.status_code}"}

    _apply_friend_metadata(uid,{'note':note},epoch)
    return {"ok": True}

def api_config():

    """设置页读取（敏感值打码）"""

    cfg = load_config()

    bark = cfg.get("bark", {})

    tg = cfg.get("telegram", {})

    key = (bark.get("key") or "").strip()

    return {

        "bark": {"enabled": bark.get("enabled", True),

                 "level": bark.get("level", "timeSensitive"),

                 "sound": bark.get("sound", ""), "group": bark.get("group", "vrc"),

                 "critical_volume": bark.get("critical_volume", 10),

                 "key_masked": (key[:4] + "****") if key else "",

                 "configured": bool(key) and not key.startswith("把你的")},

        "telegram": {"enabled": tg.get("enabled", False),

                     "bot_token_masked": ((tg.get("bot_token") or "")[:6] + "****")

                                          if tg.get("bot_token") else "",

                     "chat_id": tg.get("chat_id", "")},

        "watch_favorites": cfg.get("watch_favorites", True),

        "notify_online": cfg.get("notify_online", True),

        "notify_offline": cfg.get("notify_offline", True),

        "notify_world_change": cfg.get("notify_world_change", False),

        "notify_active": cfg.get("notify_active", True),
        "notify_active_offline": cfg.get("notify_active_offline", True),

        "notify_status": cfg.get("notify_status", False),

        "notify_desc": cfg.get("notify_desc", False),

        "notify_avatar": cfg.get("notify_avatar", False),

        "poll_seconds": cfg.get("poll_seconds", 30),

        "favorites_sync_seconds": cfg.get("favorites_sync_seconds", 90),

        "has_web_password": bool((cfg.get("web_password") or "").strip()),

    }

def api_config_set(body):

    """设置页保存：白名单字段合并写入 config.json"""

    with _lock:

        cfg = load_config()

        for path, vtype in CFG_FIELDS.items():

            if path not in body:

                continue

            val = body[path]

            try:

                val = vtype(val) if not isinstance(val, bool) else bool(val)

            except (TypeError, ValueError):

                return {"ok": False, "error": f"字段 {path} 类型错误"}

            node = cfg

            parts = path.split(".")

            for p in parts[:-1]:

                node = node.setdefault(p, {})

            node[parts[-1]] = val

        if "web_password" in body:

            newpw = str(body["web_password"]).strip()

            curpw = (cfg.get("web_password") or "").strip()

            old = str(body.get("old_password") or "").strip()

            if curpw and old != curpw:

                return {"ok": False, "error": "当前口令不正确"}

            cfg["web_password"] = newpw

        try:

            with open(CONFIG_PATH, "w", encoding="utf-8") as f:

                json.dump(cfg, f, ensure_ascii=False, indent=2)

        except OSError as e:

            return {"ok": False, "error": f"写入配置失败: {e}"}

    return {"ok": True}

def api_friendlog(qs):

    """VRCX 社交>好友日志：新的好友/删除好友/等级变动/昵称变动"""

    t = (qs.get("type") or [""])[0].strip()

    name = (qs.get("name") or [""])[0].strip()

    sql = "SELECT id, friend_id, display_name, event, ts, previous, previous_desc, " \
          "status_description FROM events WHERE event IN " \
          "('friend-add','friend-delete','name','trust')"

    args = []

    if t in ("friend-add", "friend-delete", "name", "trust"):

        sql += " AND event = ?"

        args.append(t)

    if name:

        sql += " AND (display_name LIKE ? OR previous LIKE ?)"

        args += [f"%{name}%", f"%{name}%"]

    sql += " ORDER BY ts DESC LIMIT 500"

    conn = db_ro()

    try:

        rows = [dict(r) for r in conn.execute(sql, args)]

    finally:

        conn.close()

    return {"events": rows}

def api_log_delete(body):

    rid = body.get("id")

    conn = sqlite3.connect(DB_PATH)

    try:

        conn.execute("DELETE FROM events WHERE id=?", (rid,))

        conn.commit()

    finally:

        conn.close()

    return {"ok": True}

def api_friend_delete(body):

    """VRCX 删除好友: DELETE auth/user/friends/{userId}"""

    uid = (body.get("id") or "").strip()

    if not uid.startswith("usr_"):

        return {"ok": False, "error": "无效的用户 id"}

    client = VRChatClient(load_config())

    try:

        r = client.s.delete(f"{BASE}/auth/user/friends/{uid}", timeout=20)

    except requests.RequestException as e:

        return {"ok": False, "error": f"网络错误: {e}"}

    if r.status_code not in (200, 204):

        return {"ok": False, "error": f"HTTP {r.status_code}"}

    conn = sqlite3.connect(DB_PATH)

    try:

        conn.execute("UPDATE friends_all SET in_roster=0 WHERE friend_id=?", (uid,))

        conn.execute("DELETE FROM friends_current WHERE friend_id=?", (uid,))

        conn.commit()

    finally:

        conn.close()

    return {"ok": True}

def api_favgroups(qs):

    """VRCX 收藏&分组: 收藏夹分组 + 各组成员"""

    t = (qs.get("type") or ["friend"])[0]

    if t not in ("friend", "world", "avatar"):

        t = "friend"

    client = VRChatClient(load_config())

    groups = []

    try:

        r = client.s.get(f"{BASE}/favorite/groups", params={"type": t, "n": "50"},

                         timeout=20)

        if r.status_code == 200:

            for g in r.json():

                groups.append({"id": g.get("id"),
                               "name": g.get("name") or "",
                               "displayName": g.get("displayName") or g.get("name") or "",

                               "memberCount": g.get("memberCount"),

                               "visibility": g.get("visibility") or ""})

    except requests.RequestException:

        pass

    items = []

    try:

        r2 = client.s.get(f"{BASE}/favorites", params={"type": t, "n": "100"}, timeout=25)

        if r2.status_code == 200:

            items = r2.json()

    except requests.RequestException:

        pass

    conn = db_ro()

    try:

        name_map = {r["friend_id"]: r["display_name"] for r in

                    conn.execute("SELECT friend_id, display_name FROM friends_all")}

        thumb_map = {r["friend_id"]: (r["thumb"] or "") for r in

                     conn.execute("SELECT friend_id, thumb FROM friends_all")}

        cur_ids = {r["friend_id"] for r in conn.execute("SELECT friend_id FROM friends_current")}

    finally:

        conn.close()

    out = []

    for f in items:

        tg = f.get("tags") or []

        gname = tg[0] if tg else "Favorites"

        it = {"fav_id": f.get("id"), "fid": f.get("favoriteId"), "group": gname}

        if t == "friend":

            it["name"] = name_map.get(it["fid"], it["fid"])

            it["thumb"] = thumb_map.get(it["fid"], "")

            it["online"] = it["fid"] in cur_ids

        out.append(it)

    if t == "world":

        for it in out[:30]:

            w = fetch_world(client, it["fid"])

            it["name"] = (w or {}).get("name") or it["fid"]

            it["thumb"] = (w or {}).get("thumb") or ""

    elif t == "avatar":

        for it in out[:24]:

            try:

                rr = client.s.get(f"{BASE}/avatars/{it['fid']}", timeout=15)

                if rr.status_code == 200:

                    a = rr.json()

                    it["name"] = a.get("name") or it["fid"]

                    it["image"] = a.get("imageUrl") or ""

            except requests.RequestException:

                pass

    return {"groups": groups, "items": out, "type": t}

def api_favgroup_create(body):
    """VRChat uses pre-existing group slots; setting a name is a PUT, not POST.

    Keep the old Pi route as an adapter. Callers must identify the empty slot.
    """
    if not body.get('group') or not str(body.get('name') or '').strip():
        return {'ok':False,'error':'请选择空的收藏夹并填写名称'}
    return api_favorite_op(dict(body,op='rename_group',displayName=str(body['name']).strip()))

def api_mutual_graph():
    epoch = _ensure_scope()

    """上游 Charts/MutualFriends 的 Pi 等价数据：好友两两共同好友数（mutuals API）"""

    client = VRChatClient(load_config())

    conn = db_ro()

    try:

        friends = [dict(r) for r in conn.execute(

            "SELECT friend_id, display_name FROM friends_all ORDER BY display_name LIMIT 60")]

    finally:

        conn.close()

    name = {f["friend_id"]: f["display_name"] for f in friends}

    hit = _mutual_cache.get("data")

    if hit and time.time() - _mutual_cache.get("ts", 0) < 900:

        return hit

    # 逐好友拉 mutuals/friends 名单，构造真实邻接（上游 MutualFriends 同数据源，限 40 人防限流）

    friends = friends[:40]

    adj = {fid: set() for fid in name}

    for a in friends:

        try:

            r = client.s.get(f"{BASE}/users/{a['friend_id']}/mutuals/friends",

                             params={"n": "100"}, timeout=20)

            if r.status_code != 200:

                continue

            for x in r.json():

                xid = x.get("id")

                if xid in adj:

                    adj[a["friend_id"]].add(xid)

                    adj[xid].add(a["friend_id"])

        except requests.RequestException:

            continue

    edges = [{"a": name[a], "b": name[b]}

             for a, s in adj.items() for b in s if a < b]

    out = {"edges": edges}

    with _SESSION_SCOPE.lock:
        if epoch != _ensure_scope():
            return {"error": "账号会话已变更，请刷新"}
        _mutual_cache.update({"ts": time.time(), "data": deepcopy(out)})

    return out

class _TupleTransport:

    """把 requests.Session 适配成后端服务期待的 (status, json) 元组传输接口。

    （上游契约测试用 FakeTransport 同形状；生产走本适配器，架构=ADR-0001 adapter 层）"""

    BASE = "https://api.vrchat.cloud/api/1/"

    def __init__(self, session):

        self.s = session

    def _call(self, method, path, **kw):

        kw.setdefault("timeout", 25)

        r = getattr(self.s, method)(self.BASE + path, **kw)

        try:

            j = r.json()

        except ValueError:

            j = {}

        return r.status_code, j

    def get(self, path, headers=None, params=None):

        return self._call("get", path, headers=headers, params=params)

    def post(self, path, json=None, headers=None):

        return self._call("post", path, json=json, headers=headers)

    def put(self, path, json=None, headers=None):

        return self._call("put", path, json=json, headers=headers)

    def delete(self, path, headers=None):

        return self._call("delete", path, headers=headers)

def api_favorite_op(body):

    """收藏写操作: add/remove/rename_group/clear_group（上游 favorite.js 端点族）"""

    op = (body.get("op") or "").strip()

    client = VRChatClient(load_config())

    from favorites import FavoriteService

    me = (get_self(client) or {}).get("id") or ""

    svc = FavoriteService(transport=_TupleTransport(client.s), current_user_id=me)

    if op == "add":

        r = svc.add(body.get("type", "friend"), body.get("favoriteId", ""),

                    group=body.get("group"))

    elif op == "remove":

        r = svc.remove(body.get("objectId", ""))

    elif op == "rename_group":

        r = svc.save_group(body.get("type", "friend"), body.get("group", ""),

                           display_name=body.get("displayName"),

                           visibility=body.get("visibility"))

    elif op == "clear_group":

        r = svc.clear_group(body.get("type", "friend"), body.get("group", ""))

    else:

        return {"ok": False, "error": "未知操作"}

    return {"ok": bool(r.ok), "error": getattr(r, "raw", None) if not r.ok else None}

def api_notification_act(body):

    """通知交互: accept/hide/see/delete/invite/request_invite/invite_response"""

    op = (body.get("op") or "").strip()

    nid = (body.get("id") or "").strip()

    client = VRChatClient(load_config())

    from notifications import NotificationService

    svc = NotificationService(transport=_TupleTransport(client.s))

    if op == "accept":

        r = svc.accept_friend_request(nid)

    elif op == "hide":

        r = svc.hide(nid)

    elif op == "see":

        r = svc.see(nid)

    elif op == "delete":

        r = svc.delete(nid)

    elif op == "invite":

        r = svc.invite(body.get("userId", ""), body.get("message") or None)

    elif op == "request_invite":

        r = svc.request_invite(body.get("userId", ""), body.get("message") or None)

    elif op == "invite_response":

        r = svc.invite_response(body.get("inviteId", ""), body.get("response", "accept"))

    else:

        return {"ok": False, "error": "未知操作"}

    return {"ok": bool(r.ok), "error": (r.raw or {}).get("error") if not r.ok and isinstance(r.raw, dict) else None}

def _preset_store():

    from status_presets import StatusPresetStore

    return StatusPresetStore(db_path=DB_PATH)

def api_presets_get():

    return {"presets": _preset_store().list()}

def api_preset_add(body):

    r = _preset_store().add((body.get("status") or "").strip(),

                            (body.get("desc") or "").strip())

    return {"ok": r in ("ok", "exists"), "result": r}

def api_preset_remove(body):

    _preset_store().remove(int(body.get("index", 0)))

    return {"ok": True}

_vrc_status_cache = {"ts": 0, "data": None}

def api_vrc_status():

    import time as _t

    if _t.time() - _vrc_status_cache["ts"] < 120 and _vrc_status_cache["data"]:

        return _vrc_status_cache["data"]

    from vrc_status import fetch_vrc_status

    try:

        data = fetch_vrc_status()

    except requests.RequestException as e:

        data = {"issue": True, "summary": f"无法获取服务状态（{e.__class__.__name__}）",

                "indicator": "unknown", "updated": None, "fetch_error": True}

    except ValueError as e:

        data = {"issue": True, "summary": "服务状态解析失败", "indicator": "unknown",

                "updated": None, "fetch_error": True}

    _vrc_status_cache.update({"ts": _t.time(), "data": data})

    return data

def api_group(qs):

    gid = (qs.get("id") or [""])[0].strip()

    if not gid.startswith("grp_"):

        return {"error": "无效的群组 id"}

    client = VRChatClient(load_config())

    from group_client import get_group

    g = get_group(client.s, gid)

    if not g:

        return {"error": "获取群组信息失败"}

    return {"group": g}

def api_invite_messages(mt="invite"):

    """上游 inviteMessages: GET message/{uid}/{messageType}"""

    client = VRChatClient(load_config())

    try:

        r = client.s.get(f"{BASE}/message/{me_id()}/{mt}", timeout=20)

        if r.status_code != 200:

            return {"messages": [], "error": f"HTTP {r.status_code}"}

        j = r.json()

        out = []

        if isinstance(j, list):

            for m in j:

                out.append({"slot": m.get("slot"), "message": m.get("message") or ""})

        return {"messages": out}

    except requests.RequestException as e:

        return {"messages": [], "error": f"网络错误: {e}"}

def me_id():

    s = get_self(VRChatClient(load_config()))

    return (s or {}).get("id") or ""

def api_group_search(qs):

    q = ((qs.get("q") or [""])[0] or "").strip()

    if not q:

        return {"groups": []}

    client = VRChatClient(load_config())

    try:

        r = client.s.get(f"{BASE}/groups", params={"search": q, "n": "12"}, timeout=25)

        items = r.json() if r.status_code == 200 else []

    except requests.RequestException as e:

        return {"groups": [], "error": f"网络错误: {e}"}

    return {"groups": [{"id": g.get("id"), "name": g.get("name"),

                        "icon": g.get("iconUrl") or g.get("thumbnailUrl") or "",

                        "members": g.get("memberCount")} for g in items]}

def api_group_leave(body):
    gid = (body.get("id") or "").strip()
    if not gid.startswith("grp_"):
        return {"ok": False, "error": "无效的群组 id"}
    if body.get("confirm") != "是，退出":
        return {"ok": False, "error": "缺少确认"}
    client = VRChatClient(load_config())
    me = (get_self(client) or {}).get("id")
    if not me:
        return {"ok": False, "error": "登录已过期"}
    from group_client import leave_group
    r = leave_group(client.s, gid, me)
    return {"ok": bool(r.ok), "error": (r.raw or "") if not r.ok else None}

def api_group_members(qs):
    gid = (qs.get("id") or [""])[0].strip()
    if not gid.startswith("grp_"):
        return {"error": "无效的群组 id"}
    client = VRChatClient(load_config())
    from group_members import get_members
    return get_members(client.s, gid)

def api_backup(qs):
    # GET always lists backups; creation belongs to the POST-only operation.
    files = sorted(
        (f for f in os.listdir(os.path.join(DIR, "backups")) if f.endswith(".db")),
        reverse=True) if os.path.isdir(os.path.join(DIR, "backups")) else []
    return {"backups": files}

def api_backup_op(body):
    if (body.get("op") or "") == "create":
        from backup import create_backup
        try:
            f = create_backup(DB_PATH, os.path.join(DIR, "backups"))
            return {"ok": True, "file": os.path.basename(f)}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "未知操作"}

def api_backup_restore(body):
    fname = os.path.basename(body.get("file") or "")
    if not fname.endswith(".db"):
        return {"ok": False, "error": "无效的备份文件名"}
    from backup import restore_backup
    p = os.path.join(DIR, "backups", fname)
    try:
        restore_backup(DB_PATH, p)
        return {"ok": True}
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

def api_export(qs):
    """Account-scoped export envelope; HTTP may send it as an attachment."""
    kind = (qs.get("kind") or ["friends.csv"])[0]
    if kind == "friends.csv":
        from export_import import export_friends_csv
        content = export_friends_csv(DB_PATH)
        content_type = "text/csv"
    elif kind == "events.json":
        conn = db_ro()
        try:
            rows = [dict(r) for r in conn.execute("SELECT display_name, event, ts, duration, world_name, location, status_description FROM events ORDER BY ts DESC LIMIT 10000")]
        finally:
            conn.close()
        content = json.dumps({"events":rows},ensure_ascii=False)
        content_type = "application/json"
    else:
        return {"error":"未知导出类型"}
    return {"filename":"vrcx-cloud-"+kind,"content_type":content_type,"content":content}


def api_export_events():
    return api_export({"kind":["events.json"]})

def import_favorite_groups_via_session(body):
    from favgroup_import import import_favorite_groups
    ftype = body.get("type") or "friend"
    client = VRChatClient(load_config())
    r = import_favorite_groups(client.s, {"type": ftype, "groups": body.get("groups") or []},
                               my_id="")
    return {"ok": r["fail_count"] == 0, "ok_count": r["ok_count"], "fail_count": r["fail_count"]}

ADAPTER_SHIM_JS = """(function () {
    'use strict';
    window.LINUX = true;
    window.WINDOWS = false;
    if (window.crypto && !window.crypto.randomUUID) {
        window.crypto.randomUUID = function () {
            var b = window.crypto.getRandomValues(new Uint8Array(16));
            b[6] = (b[6] & 15) | 64;
            b[8] = (b[8] & 63) | 128;
            var h = Array.prototype.map.call(b, function (x) {
                return ('0' + x.toString(16)).slice(-2);
            }).join('');
            return h.slice(0, 8) + '-' + h.slice(8, 12) + '-4' + h.slice(13, 16) +
                '-a' + h.slice(17, 20) + '-' + h.slice(20);
        };
    }
    window.__errs = [];
    function __pushErr(s) {
        window.__errs.push(s);
        if (window.__errs.length > 50) window.__errs.shift();
    }
    window.addEventListener('unhandledrejection', function (e) {
        var r = e.reason;
        __pushErr('REJ: ' + (r && r.message ? r.message + ' :: ' + String(r.stack || '').slice(0, 500) : String(r)));
    });
    window.addEventListener('error', function (e) {
        __pushErr('ERR: ' + e.message + ' @ ' + e.filename + ':' + e.lineno);
    });
    var _ce = console.error.bind(console);
    console.error = function () {
        try {
            var parts = Array.prototype.map.call(arguments, function (a) {
                return a && a.message ? a.message + ' :: ' + String(a.stack || '').slice(0, 300) : String(a);
            });
            window.__errs.push('CE: ' + parts.join(' ').slice(0, 600));
        } catch (e) {}
        _ce.apply(console, arguments);
    };
    window.__logs = [];
    ['log', 'warn'].forEach(function (level) {
        var orig = console[level].bind(console);
        console[level] = function () {
            try {
                var parts = Array.prototype.map.call(arguments, function (a) {
                    return typeof a === 'string' ? a : JSON.stringify(a).slice(0, 120);
                });
                window.__logs.push(level[0].toUpperCase() + ': ' + parts.join(' ').slice(0, 250));
                if (window.__logs.length > 60) window.__logs.shift();
            } catch (e) {}
            orig.apply(console, arguments);
        };
    });
    var BASE = '/adapter';
    function postJSON(url, payload, tried) {
        return fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        }).then(function (r) { return r.json(); })
          .catch(function (e) {
              if (!tried) return postJSON(url, payload, true);
              throw e;
          });
    }
    function normArgs(args) {
        if (args && typeof args.entries === 'function') return Object.fromEntries(args);
        return args || null;
    }
    /* 深转换：上游 LINUX 分支传 Map 作参数，JSON.stringify(Map) 会变成 {}，
     * 必须在序列化前递归还原为普通对象。 */
    function deepNorm(v) {
        if (v instanceof Map) return deepNorm(Object.fromEntries(v));
        if (Array.isArray(v)) return v.map(deepNorm);
        if (v && typeof v === 'object') {
            var o = {};
            Object.keys(v).forEach(function (k) { o[k] = deepNorm(v[k]); });
            return o;
        }
        return v;
    }
    /* 上游非 Windows 启动路径（src/plugins/interopApi.js）会用 InteropApi Proxy
     * 覆盖 window.WebApi/SQLite，所有 .NET 类方法统一经
     * window.interopApi.callDotNetMethod(class, method, argsArray) 走 IPC。
     * Pi 端由 /adapter/dotnet 分发到等价后端实现（ADR-0002）。 */
    window.interopApi = {
        callDotNetMethod: function (className, methodName, args) {
            return postJSON(BASE + '/dotnet', {
                className: className,
                methodName: methodName,
                args: deepNorm(args === undefined ? [] : (Array.isArray(args) ? args : [args]))
            }).then(function (r) {
                if (r && r.__error) { throw new Error(r.message || 'dotnet adapter error'); }
                return r ? r.result : null;
            });
        }
    };
    /* window.electron：Electron preload 暴露的本机桥（src-electron/preload.js）。
     * Pi 浏览器无 Electron：getArch/getNoUpdater 给出真实值，其余本机能力空实现。 */
    var noop = function () { return Promise.resolve(null); };
    window.electron = {
        getArch: function () { return Promise.resolve('arm'); },
        getNoUpdater: function () { return Promise.resolve(true); },
        getClipboardText: function () { return Promise.resolve(''); },
        setTrayIconNotification: noop,
        openFileDialog: noop,
        openDirectoryDialog: noop,
        desktopNotification: noop,
        restartApp: noop,
        getOverlayWindow: noop,
        updateVr: noop,
        onWindowPositionChanged: noop,
        onWindowSizeChanged: noop,
        onWindowStateChange: noop,
        onBrowserFocus: noop,
        ipcRenderer: { on: function () {}, invoke: noop }
    };
    /* 兜底直接绑定（早期代码 / Overlay 场景） */
    window.WebApi = {
        ExecuteJson: function (requestJson) {
            return window.interopApi.callDotNetMethod('WebApi', 'ExecuteJson', [requestJson]);
        },
        ClearCookies: function () { return postJSON(BASE + '/cookies/clear', {}); },
        GetCookies: function () { return fetch(BASE + '/cookies').then(function (r) { return r.text(); }); },
        SetCookies: function (cookie) { return postJSON(BASE + '/cookies/set', { cookie: cookie }); }
    };
    window.SQLite = {
        ExecuteJson: function (sql, args) {
            return window.interopApi.callDotNetMethod('SQLite', 'ExecuteJson', [sql, normArgs(args)]);
        },
        Execute: function (sql, args) {
            return window.interopApi.callDotNetMethod('SQLite', 'Execute', [sql, normArgs(args)]);
        },
        ExecuteNonQuery: function (sql, args) {
            return window.interopApi.callDotNetMethod('SQLite', 'ExecuteNonQuery', [sql, normArgs(args)]);
        }
    };
})();"""


def adapter_webapi_execute_json(request_json, vrc_session):
    import json as _json
    try:
        options = _json.loads(request_json)
    except ValueError:
        return {"status": -1, "message": "bad request json"}
    url = options.get("url") or ""
    if not url.startswith("http"):
        url = "https://api.vrchat.cloud/api/1/" + url.lstrip("/")
    method = (options.get("method") or "GET").upper()
    headers = options.get("headers") or {}
    body = options.get("body")
    try:
        r = vrc_session.request(method, url,
                                data=body if method not in ("GET", "HEAD") else None,
                                headers=headers, timeout=15)
        return {"status": r.status_code, "message": r.text}
    except requests.RequestException as e:
        return {"status": -1, "message": str(e)}

_AT_PARAM_RE = re.compile(r"[@$]([A-Za-z_][A-Za-z0-9_]*)")

def _sqlite_translate(sql, args):
    """上游用 @name/$name 命名参数；pysqlite 只认 :name，做等价翻译。"""
    if isinstance(args, dict):
        sql = _AT_PARAM_RE.sub(r":\1", sql)
        args = {k.lstrip("@$:"): v for k, v in args.items()}
        return sql, args
    return sql, (args or [])

def adapter_sqlite_upstream(payload):
    conn = None
    try:
        sql, args = _sqlite_translate(payload.get("sql") or "", payload.get("args"))
        conn = sqlite3.connect(UPSTREAM_DB_PATH, timeout=15)
        cur = conn.execute(sql, args)
        # .NET ExecuteJson 序列化为行数组（上游回调按 dbRow[0] 索引访问）
        rows = [list(r) for r in cur.fetchall()]
        conn.commit()
        return {"status": 0, "message": json.dumps(rows, ensure_ascii=False)}
    except Exception as e:
        print(f"[adapter][sqlite-error] {e} | sql={sql[:200]} | "
              f"args={str(args)[:200]}", flush=True)
        return {"status": 1, "message": str(e)}
    finally:
        if conn:
            conn.close()

def adapter_sqlite_nonquery(payload):
    conn = None
    try:
        sql, args = _sqlite_translate(payload.get("sql") or "", payload.get("args"))
        conn = sqlite3.connect(UPSTREAM_DB_PATH, timeout=15)
        with _SQLITE_WRITE_LOCK:
            cur = conn.execute(sql, args)
            conn.commit()
        return {"status": 0, "message": str(cur.rowcount)}
    except Exception as e:
        return {"status": 1, "message": str(e)}
    finally:
        if conn:
            conn.close()

def _upstream_app_version():
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(DIR, "Version"), os.path.join(here, "Version"),
                 os.path.join(here, "..", "..", "vendor", "VRCX", "Version")):
        try:
            with open(os.path.normpath(cand), "r", encoding="utf-8") as f:
                v = f.read().strip()
                if v:
                    return v
        except OSError:
            continue
    return "unknown"

UPSTREAM_APP_VERSION = _upstream_app_version()

VRCX_STORAGE_PATH = os.path.join(os.path.dirname(UPSTREAM_DB_PATH),
                                 "vrcx-storage.json")
_storage_lock = threading.Lock()

def _storage_load():
    try:
        with open(VRCX_STORAGE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _storage_save(data):
    tmp = VRCX_STORAGE_PATH + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, VRCX_STORAGE_PATH)

_COOKIE_SAVE_LOCK = threading.Lock()
_SQLITE_WRITE_LOCK = threading.Lock()
_STATUS_CACHE = {"ts": 0.0, "r": None}
_GZIP_CACHE = {}  # path -> (mtime, gzipped_bytes)

def _webapi_proxy(request_json):
    # 锁绝不跨越网络 I/O：登录页每分钟轮询 status.vrchat.com（该域名在 Pi
    # 网络下超时 30s×重试），曾把登录请求全部堵死在锁后（"点登录没反应"）。
    try:
        opts = json.loads(request_json) if request_json else {}
    except ValueError:
        opts = {}
    url = opts.get("url") or ""
    method = (opts.get("method") or "GET").upper()

    if "status.vrchat.com" in url:
        # 公开状态页：负缓存 300s/成功 60s（Pi 侧该域名被 DNS 污染不可达）
        now = time.time()
        cached = _STATUS_CACHE.get("r")
        if cached and now - _STATUS_CACHE.get("ts", 0) < (
                60 if cached["status"] == 200 else 300):
            return cached
        try:
            r = requests.get(url, timeout=8,
                             headers={"User-Agent": "VRCX Cloud Status/1.0.0"})
            result = {"status": r.status_code, "message": r.text}
        except requests.RequestException as e:
            result = {"status": -1, "message": str(e)}
        _STATUS_CACHE["ts"] = now
        _STATUS_CACHE["r"] = result
    else:
        client = _ui_client()
        result = adapter_webapi_execute_json(request_json, client.s)
        try:
            with _COOKIE_SAVE_LOCK:
                client._save_cookies(UI_AUTH_PATH)  # Set-Cookie 只落 UI 会话
        except Exception:
            pass

    print(f"[adapter][webapi] {result.get('status')} {method} "
          f"{url.split('?')[0][-60:]}", flush=True)
    return result

def adapter_dotnet(body):
    """上游 Electron preload 的 callDotNetMethod IPC 等价分发（ADR-0002）。"""
    cls = body.get("className") or ""
    meth = body.get("methodName") or ""
    args = body.get("args") or []
    if os.environ.get("VRCX_ADAPTER_TRACE"):
        detail = str(args[0])[:60] if args else ""
        if cls == "SQLite" and len(args) > 1 and isinstance(args[1], dict):
            # 只打查询键名，不打参数值（防凭据进日志）
            detail += " keys=" + str(list(args[1].values()))[:60]
        print(f"[adapter] {cls}.{meth} {detail}", flush=True)

    def arg(i):
        return args[i] if len(args) > i else None

    try:
        if cls == "SQLite":
            payload = {"sql": arg(0) or "", "args": arg(1)}
            if meth == "ExecuteJson":
                r = adapter_sqlite_upstream(payload)
                if r["status"] != 0:
                    raise RuntimeError(r["message"])
                return {"result": r["message"]}
            if meth == "Execute":
                r = adapter_sqlite_upstream(payload)
                if r["status"] != 0:
                    raise RuntimeError(r["message"])
                return {"result": json.loads(r["message"])}
            if meth == "ExecuteNonQuery":
                r = adapter_sqlite_nonquery(payload)
                if r["status"] != 0:
                    raise RuntimeError(r["message"])
                return {"result": int(r["message"])}
        elif cls == "WebApi":
            if meth == "ClearCookies":
                return {"result": adapter_cookies_clear()["message"]}
            if meth == "GetCookies":
                client = _ui_client()
                return {"result": json.dumps([
                    {"name": c.name, "value": c.value, "domain": c.domain,
                     "path": c.path, "secure": c.secure}
                    for c in client.s.cookies])}
            if meth == "SetCookies":
                return {"result": adapter_cookies_set(
                    {"cookie": arg(0) or ""})["message"]}
            if meth in ("ExecuteJson", "Execute"):
                req = arg(0)
                if meth == "Execute" and isinstance(req, dict):
                    req = json.dumps(req)
                return {"result": json.dumps(
                    _webapi_proxy(req or ""), ensure_ascii=False)}
        elif cls == "VRCXStorage":
            with _storage_lock:
                data = _storage_load()
                if meth == "Get":
                    return {"result": data.get(arg(0) or "")}
                if meth == "Set":
                    data[arg(0) or ""] = str(arg(1))
                    _storage_save(data)
                    return {"result": None}
                if meth == "Remove":
                    data.pop(arg(0) or "", None)
                    _storage_save(data)
                    return {"result": None}
                if meth == "GetAll":
                    return {"result": json.dumps(data, ensure_ascii=False)}
                if meth == "Save":
                    _storage_save(data)
                    return {"result": None}
        elif cls in ("AppApi", "AppApiElectron", "AppApiVrElectron"):
            if meth == "GetVersion":
                # .NET AppApi.GetVersion 返回 VRCX 自身版本；Pi 即锁定的上游版本
                return {"result": UPSTREAM_APP_VERSION}
            # 其余本机 App 能力（窗口/托盘/启动游戏等）Pi 无对应物：诚实 null 并留痕
            print(f"[adapter] {cls}.{meth} -> null (no local capability)",
                  flush=True)
            return {"result": None}
        elif cls == "LogWatcher":
            # 上游 Linux 语义：无游戏日志时返回空列表（gameLog 按迭代消费）
            if meth == "Get":
                return {"result": []}
            print(f"[adapter] LogWatcher.{meth} -> null (no local capability)",
                  flush=True)
            return {"result": None}
        elif cls in ("Discord", "AssetBundleManager",
                     "SystemMonitorElectron", "VRCXNetInterface"):
            print(f"[adapter] {cls}.{meth} -> null (no local capability)",
                  flush=True)
            return {"result": None}
        print(f"[adapter] {cls}.{meth} not implemented", flush=True)
        return {"__error": True, "message": f"{cls}.{meth} not implemented"}
    except Exception as e:
        return {"__error": True, "message": str(e)}

def _sqlite_rows(payload):
    r = adapter_sqlite_upstream(payload)
    if r.get("status") == 0:
        try:
            return {"rows": json.loads(r["message"])}
        except ValueError:
            return {"rows": []}
    return {"rows": [], "error": r.get("message")}

def adapter_webapi_endpoint(body):
    return _webapi_proxy(body.get("request") or "")

# 上游 UI 独立会话存储：与监控的 auth.json 彻底隔离。
# 上游界面 clearCookies/登出只清这里，绝不触碰监控会话（D-P1-S4）。
UI_AUTH_PATH = os.path.join(os.path.dirname(AUTH_PATH), "auth-ui.json")

# 单一常驻 UI 会话：等价 Electron 的持续 CookieContainer（D-P1-S5）。
# 登录链（Basic → emailOtp verify → 拿正式 auth cookie）依赖 cookie 连续性，
# 文件中转会断链；常驻内存会话 + 变更后落盘（供监控跟随）。
_UI_SESSION = {"client": None}
_UI_SESSION_LOCK = threading.RLock()

def _ui_client():
    _ensure_scope()
    with _UI_SESSION_LOCK:
        if _UI_SESSION["client"] is None:
            _UI_SESSION["client"] = VRChatClient(load_config())
        return _UI_SESSION["client"]

def adapter_cookies_list():
    client = _ui_client()
    return [{"name": c.name, "value": c.value, "domain": c.domain}
            for c in client.s.cookies]

def _cookies_set_on(client, name, value):
    client.s.cookies.set(name, value, domain="api.vrchat.cloud")

def adapter_cookies_set(body):
    cookie = body.get("cookie") or ""
    client = _ui_client()
    added = 0
    # 上游 WebApi.SetCookies 传 JSON 数组（.NET CookieContainer 语义）或分号串
    try:
        items = json.loads(cookie)
        if isinstance(items, list):
            for it in items:
                if isinstance(it, dict) and it.get("name"):
                    _cookies_set_on(client, it["name"], str(it.get("value", "")))
                    added += 1
    except ValueError:
        for part in cookie.split(";"):
            part = part.strip()
            if "=" in part:
                k, _, v = part.partition("=")
                _cookies_set_on(client, k.strip(), v.strip())
                added += 1
    client._save_cookies(UI_AUTH_PATH)
    _invalidate_session()
    return {"status": 0, "message": f"{added} cookies set"}

def adapter_cookies_clear():
    with _UI_SESSION_LOCK:
        client = _ui_client()
        client.s.cookies.clear()
        client._save_cookies(UI_AUTH_PATH)
        _invalidate_session()
    return {"status": 0, "message": "cookies cleared"}

UPSTREAM_DIST_CANDIDATES = (
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "upstream-dist"),
    os.path.expanduser("~/.local/share/vrcx-cloud/upstream-dist"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "..", "..", "vendor", "VRCX", "src", "upstream-dist"),
)

_STATIC_TYPES = {".html": "text/html", ".js": "application/javascript",
                 ".css": "text/css", ".json": "application/json",
                 ".png": "image/png", ".jpg": "image/jpeg",
                 ".jpeg": "image/jpeg", ".svg": "image/svg+xml",
                 ".ico": "image/x-icon", ".woff": "font/woff",
                 ".woff2": "font/woff2", ".ttf": "font/ttf",
                 ".map": "application/json", ".webp": "image/webp",
                 ".txt": "text/plain"}

def _find_upstream_dist():
    for cand in UPSTREAM_DIST_CANDIDATES:
        p = os.path.normpath(cand)
        if os.path.isfile(os.path.join(p, "index.html")):
            return p
    return None

def _avatar_from_db(uid):

    'friends_all.thumb 兜底（监控每轮刷新，列表预画壳用的就是它）——\n\n    VRChat 实时 /users/{uid} 对部分用户不回头像 URL'



    try:

        conn = db_ro()

        try:

            r = conn.execute("SELECT thumb FROM friends_all WHERE friend_id=?", (uid,)).fetchone()

            return (r["thumb"] or "") if r else ""

        finally:

            conn.close()

    except sqlite3.Error:

        return ""

# ---------- 隧道流量统计（左栏面板 /api/net-stats） ----------

# 数据源 = vrc-tunnel 的 ssh 进程 /proc/<pid>/io 的 wchar（ssh 经手字节 ≈ 隧道上+下行总量，
# 不含 kiosk/整机杂项——正是服务器流量包关心的那部分）。ssh 重启后计数器归零，
# 采样器按"增量非负"处理，持久化文件保证跨 web 重启的今日/24h/总计连续性。

NET_FILE = os.path.join(DIR, "netstats.json")

_NET_LOCK = threading.Lock()

_NET_SAMPLES = []   # [(ts, 增量字节)]，滚动保留 25h

_NET_TOTAL = 0      # 累计总量（持久化）

_NET_LAST = None    # (ts, wchar)

_SYS = {"mem_pct": None, "mem_used_mb": None, "cpu_pct": None, "down_bps": None, "up_bps": None, "poll": None}

_IO_LAST = None     # (ts, rchar, wchar)

def _send_icon(size):

    fp = os.path.join(DIR, f"icon-{size}.png")

    if os.path.isfile(fp):

        with open(fp, "rb") as f:

            return f.read()

    return b"{\"error\": " + str(size).encode() + b"}"

def _tunnel_io():

    # 隧道进程 (rchar, wchar)：近似下载/上传字节

    import glob

    for d in glob.glob("/proc/[0-9]*"):

        try:

            with open(d + "/cmdline", "rb") as f:

                parts = f.read().decode("utf-8", "ignore").split("\0")

            is_tunnel = "-D" in parts and "127.0.0.1:1080" in parts

            if not parts or not parts[0].endswith("ssh") or not is_tunnel:

                continue

            rch = wch = None

            with open(d + "/io", "r") as f:

                for line in f:

                    if line.startswith("rchar"):

                        rch = int(line.split()[1])

                    elif line.startswith("wchar"):

                        wch = int(line.split()[1])

            if rch is not None and wch is not None:

                return rch, wch

        except (OSError, ValueError, IndexError):

            continue

    return None

def _pi_mem_pct():

    try:

        with open("/proc/meminfo", "r") as f:

            info = {}

            for l in f:

                if ":" in l and len(l.split()) > 1:

                    info[l.split(":")[0]] = int(l.split()[1])

        total = info.get("MemTotal", 0)

        avail = info.get("MemAvailable", info.get("MemFree", 0))

        if not total:

            return None, None

        return round((1 - avail / total) * 100, 1), round((total - avail) / 1024)

    except (OSError, ValueError):

        return None

_CPU_LAST = {"idle": None, "total": None}

def _pi_cpu_tick():

    # /proc/stat 差值算 CPU 占用；首次调用返回 None（采样器周期调用后就有值）

    try:

        with open("/proc/stat", "r") as f:

            vals = [int(x) for x in f.readline().split()[1:]]

        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)

        total = sum(vals)

        pct = None

        if _CPU_LAST["idle"] is not None and total > _CPU_LAST["total"]:

            pct = round((1 - (idle - _CPU_LAST["idle"]) / (total - _CPU_LAST["total"])) * 100, 1)

        _CPU_LAST["idle"] = idle

        _CPU_LAST["total"] = total

        return pct

    except (OSError, ValueError, IndexError):

        return None

def _tunnel_wchar():

    import glob

    for d in glob.glob("/proc/[0-9]*"):

        try:

            with open(d + "/cmdline", "rb") as f:

                parts = f.read().decode("utf-8", "ignore").split("\0")

            is_tunnel = "-D" in parts and "127.0.0.1:1080" in parts

            if not parts or not parts[0].endswith("ssh") or not is_tunnel:

                continue

            with open(d + "/io", "r") as f:

                for line in f:

                    if line.startswith("wchar"):

                        return int(line.split()[1])

        except (OSError, ValueError, IndexError):

            continue

    return None

def _net_load():

    global _NET_SAMPLES, _NET_TOTAL

    try:

        with open(NET_FILE, "r", encoding="utf-8") as f:

            data = json.load(f)

        cutoff = time.time() - 90000

        _NET_SAMPLES = [tuple(x) for x in data.get("samples", []) if x[0] > cutoff]

        _NET_TOTAL = data.get("total", 0)

    except (OSError, ValueError):

        pass

def _net_save():

    try:

        with _NET_LOCK:

            snap = {"samples": _NET_SAMPLES, "total": _NET_TOTAL}

        with open(NET_FILE + ".tmp", "w", encoding="utf-8") as f:

            json.dump(snap, f)

        os.replace(NET_FILE + ".tmp", NET_FILE)

    except (OSError, TypeError):

        pass

def _net_sampler():

    global _NET_LAST, _NET_TOTAL, _IO_LAST

    _net_load()

    while True:

        try:

            now = time.time()

            _m = _pi_mem_pct()

            _SYS["mem_pct"], _SYS["mem_used_mb"] = _m

            _SYS["cpu_pct"] = _pi_cpu_tick()

            io = _tunnel_io()

            if io is not None:

                rch, wch = io

                if _IO_LAST and now > _IO_LAST[0] and rch >= _IO_LAST[1] and wch >= _IO_LAST[2]:

                    dt = now - _IO_LAST[0]

                    _SYS["down_bps"] = round((rch - _IO_LAST[1]) / dt, 1)

                    _SYS["up_bps"] = round((wch - _IO_LAST[2]) / dt, 1)

                _IO_LAST = (now, rch, wch)

            _SYS["poll"] = int((load_config() or {}).get("poll_seconds") or 30)

            w = _tunnel_wchar()

            if w is not None:

                with _NET_LOCK:

                    if _NET_LAST and now > _NET_LAST[0] and w >= _NET_LAST[1]:

                        delta = w - _NET_LAST[1]

                        _NET_SAMPLES.append((now, delta))

                        _NET_TOTAL += delta

                    _NET_LAST = (now, w)

                    cutoff = now - 90000

                    while _NET_SAMPLES and _NET_SAMPLES[0][0] < cutoff:

                        _NET_SAMPLES.pop(0)

                if int(now) % 60 < 20:

                    _net_save()

        except Exception:

            import traceback, sys as _sys

            traceback.print_exc(file=_sys.stderr)

        time.sleep(20)

def _net_windows(samples, now=None, day_start=None):

    """纯聚合：samples=[(ts, 增量字节)] → {rate, today, hour1, hour24}（total 由调用方给）"""

    now = time.time() if now is None else now

    if day_start is None:

        lt = time.localtime(now)

        day_start = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))

    win = {"rate": 0.0, "today": 0, "hour1": 0, "hour24": 0}

    for ts, b in samples:

        if b < 0:

            continue

        if ts >= now - 86400:

            win["hour24"] += b

        if ts >= now - 3600:

            win["hour1"] += b

        if ts >= day_start:

            win["today"] += b

    if len(samples) >= 2:

        (t1, b1), (t2, b2) = samples[-2], samples[-1]

        if t2 > t1 and b2 >= b1:

            win["rate"] = (b2 - b1) / (t2 - t1)

    return win

def api_net_stats():

    with _NET_LOCK:

        samples = list(_NET_SAMPLES)

        total = _NET_TOTAL

    out = _net_windows(samples)

    out["total"] = total

    out["ts"] = time.time()

    out.update(_SYS)

    return out

def api_login(body):

    username = (body.get("username") or "").strip()

    password = body.get("password") or ""

    code = (body.get("code") or "").strip()

    store = bool(body.get("store", True))

    hints = {"totp": "请输入验证器 App 的动态验证码(6位)",

             "emailOtp": "请输入 VRChat 发到你邮箱的最新验证码",

             "otp": "请输入恢复代码(recovery code)"}

    with _lock:

        if code and not _login_ctx:

            return {"need_2fa": True, "kind": "emailOtp", "hint": hints["emailOtp"],

                    "error": "登录会话已重置，请先只填账号密码点一次登录（会发新验证码），再输入最新邮件里的验证码"}

        client = VRChatClient(load_config())

        kind = "totp"

        if _login_ctx:

            client.s = _login_ctx["session"]

            username = username or _login_ctx.get("username", "")

            password = password or _login_ctx.get("password", "")

            store = _login_ctx.get("store", store)

            kind = _login_ctx.get("kind", "totp")

        try:

            client.login(username, password, totp_code=code or None, store_creds=store,

                         kinds=_login_ctx.get("kinds"))

            _login_ctx.clear()

            _invalidate_session()

            return {"ok": True, "message": "登录成功！监控会在 30 秒内自动开始工作。"}

        except TwoFactorRequired as e:

            kind = ("totp" if "totp" in e.kinds

                    else "emailOtp" if "emailOtp" in e.kinds else "otp")

            _login_ctx.clear()

            _login_ctx.update({"session": client.s, "username": username,

                               "password": password, "store": store,

                               "kind": kind, "kinds": list(e.kinds)})

            return {"need_2fa": True, "kind": kind, "hint": hints[kind]}

        except SystemExit as e:

            err = str(e) or "登录失败"

            if _login_ctx:

                return {"need_2fa": True, "kind": kind, "hint": hints.get(kind), "error": err}

            return {"ok": False, "error": err}

        except Exception as e:

            return {"ok": False, "error": f"网络或接口异常: {e}"}

def api_push_test():

    cfg = load_config()

    ok = push(cfg, "🔔 vrc-watch 测试", "如果你在手机/手表上看到这条，推送链路已打通")

    return {"ok": ok}

def api_refresh():

    """网页端手动刷新：touch 触发文件，监控 1 秒内唤醒立即同步好友状态"""

    p = vrc_watch.REFRESH_FILE

    try:

        open(p, "w").close()

        return {"ok": True}

    except OSError as e:

        return {"ok": False, "error": str(e)}

# Compatibility export for callers; HTML and JS are maintained in separate files.
PAGE_HTML = (Path(__file__).parent / "templates" / "index.html").read_text(encoding="utf-8")

# 构建号由页面、脚本、样式与服务代码内容计算，所有静态资源共享版本。
# 前端每 60s 对比 /api/ui-version（实时读盘）——不一致即有新部署，自动 reload。
# 注意：部署 web.py 后必须重启 web 服务，否则旧进程会陷入重载循环。
_ASSETS = Assets(Path(__file__).parent)
UI_BUILD = _ASSETS.version()

_RENDERED_VER = None   # 当前渲染 HTML 实际注入的版本（与 UI_BUILD 同源；部署/重启后由首次渲染更新）

def _log_category(path):
    try:
        category = urlparse(path).path.split('/')[1:2]
    except ValueError:
        return '/other'
    return '/' + category[0] if category and category[0] in ('api', 'media', 'static', 'adapter') else '/other'

class Handler(BaseHTTPRequestHandler):

    server_version = "VRCX-Cloud/1.0.0"
    protocol_version = "HTTP/1.1"
    timeout = 300

    def log_message(self, fmt, *args):
        status = args[1] if fmt.startswith('"%s"') and len(args) > 1 else '-'
        status = str(status) if str(status).isdigit() else '-'
        method = getattr(self, 'command', '-')
        method = method if method in ('GET','POST','HEAD','OPTIONS','PUT','DELETE') else '-'
        log(f"web {method} {_log_category(getattr(self, 'path', '/'))} {status}")

    def _send(self, code, data, ctype="application/json", static=False):
        payload = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode("utf-8")
        compressed = "gzip" in (self.headers.get("Accept-Encoding") or "") and len(payload)>1024 and ctype in ("application/json", "text/html", "text/css", "text/javascript", "application/javascript")
        if compressed:
            payload = gzip.compress(payload)
        self.send_response(code)
        self.send_header("Content-Type", ctype if ctype.startswith('image/') else f"{ctype}; charset=utf-8")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(payload)))
        # Authenticated assets must not escape into shared proxy caches.
        self.send_header("Cache-Control", "private, max-age=31536000, immutable" if static else "no-store")
        self.send_header("Vary", "Accept-Encoding, X-Web-Token")
        if compressed:
            self.send_header("Content-Encoding", "gzip")
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _authed(self, cfg):

        pw = _access_password(cfg)

        return not pw or self.headers.get("X-Web-Token", "") == pw

    def _serve_upstream(self, rel):
        root = _find_upstream_dist()
        if not root:
            return self._send(404, {"error": "upstream dist not deployed"})
        rel = rel.split("?")[0]
        if not rel:
            rel = "index.html"
        try:
            root = Path(root).resolve()
            target = (root / rel).resolve()
            if not target.is_relative_to(root):
                return self._send(403, {"error": "forbidden"})
            if target.is_dir():
                target = (target / "index.html").resolve()
            if not target.is_relative_to(root):
                return self._send(403, {"error": "forbidden"})
            if not target.is_file():
                return self._send(404, {"error": "not found"})
        except (OSError, RuntimeError, ValueError):
            return self._send(403, {"error": "forbidden"})
        target = str(target)
        ext = os.path.splitext(target)[1].lower()
        ctype = _STATIC_TYPES.get(ext, "application/octet-stream")
        with open(target, "rb") as f:
            data = f.read()
        accepts_gzip = "gzip" in (self.headers.get("Accept-Encoding") or "")
        compressible = ext in (".js", ".css", ".html", ".json", ".svg", ".txt",
                               ".map")
        body = data
        if accepts_gzip and compressible and len(data) > 1024:
            mtime = os.path.getmtime(target)
            cached = _GZIP_CACHE.get(target)
            if not cached or cached[0] != mtime:
                buf = io.BytesIO()
                with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6) as g:
                    g.write(data)
                _GZIP_CACHE[target] = (mtime, buf.getvalue())
            body = _GZIP_CACHE[target][1]
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if body is not data:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        cache = "max-age=604800, immutable" if rel.startswith("assets/") else "no-cache"
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/healthz" and not u.query:
            return self._send(200, {"status": "ok"})
        if u.path.startswith('/media/'):
            if u.query: return self._send(404, {'error':'not found'})
            remote_path = '/media/' + u.path[len('/media/peer/'):] if u.path.startswith('/media/peer/') else None
            if remote_path is not None:
                if not MEDIA_PATH.fullmatch(remote_path): return self._send(404, {'error':'not found'})
                peer = (load_config().get('peer_url') or '').rstrip('/')
                target = relay_url(peer, remote_path, 'GET', {remote_path})
                if isinstance(target, dict): return self._send(404, {'error':'not found'})
                try:
                    with requests.get(target, timeout=8, headers=_peer_headers()) as response:
                        if response.status_code != 200 or len(response.content) > 4*1024*1024:
                            return self._send(404, {'error':'not found'})
                        data = response.content
                        kind = image_type(data)
                except (requests.RequestException, ValueError):
                    return self._send(404, {'error':'not found'})
            else:
                hit = _image_cache().read(_image_scope(), u.path)
                if hit is None: return self._send(404, {'error':'not found'})
                data, kind = hit
            return self._send(200, data, kind, static=True)
        # Browser script/link elements cannot attach X-Web-Token. Public code
        # contains no account data; data APIs retain the existing auth boundary.
        if u.path.startswith("/static/"):
            from urllib.parse import unquote
            asset = _ASSETS.resolve(unquote(u.path[len("/static/"):]))
            if not asset:
                return self._send(404, {"error": "not found"})
            path, content_type = asset
            versioned = (q.get("v") or [""])[0] == _ASSETS.version()
            return self._send(200, path.read_bytes(), content_type, static=versioned)
        cfg = load_config()
        if not self._authed(cfg):
            return self._send(401, {"error": "需要访问口令"})
        if u.path == "/adapter-shim.js":
            return self._send(200, ADAPTER_SHIM_JS.encode("utf-8"),
                              "application/javascript")
        if u.path == "/adapter/cookies":
            return self._send(200, adapter_cookies_list())
        if u.path == "/upstream" or u.path.startswith("/upstream/"):
            return self._serve_upstream(u.path[len("/upstream/"):].lstrip("/"))
        if u.path == "/api/events/stream":
            if not self._authed(cfg):
                return self._send(401, {"error": "需要访问口令"})
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            conn0 = db_ro()
            row0 = conn0.execute("SELECT MAX(id) m FROM events").fetchone()
            last_id = row0["m"] or 0
            conn0.close()
            start0 = time.time()
            try:
                while time.time() - start0 < 240:
                    conn0 = db_ro()
                    rows0 = [dict(r) for r in conn0.execute(
                        "SELECT id, friend_id, display_name, event, ts, duration, "
                        "world_name, location, status, status_description, previous, "
                        "previous_desc, previous_location, prev_state FROM events WHERE id > ? ORDER BY id", (last_id,))]
                    conn0.close()
                    for r0 in rows0:
                        last_id = max(last_id, r0["id"])
                        r0["instance_label"] = parse_location(r0.get("location") or "")[2]
                        payload0 = f"id: {r0['id']}\nevent: feed\ndata: {json.dumps(r0, ensure_ascii=False)}\n\n"
                        self.wfile.write(payload0.encode("utf-8"))
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    time.sleep(2)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        if u.path in ("/api/export", "/api/export-events") and (q.get("format") or [""])[0] != "json":
            if u.path == "/api/export-events":
                q["kind"] = ["events.json"]
            payload = api_export(q)
            if payload.get("error"):
                return self._send(400,payload)
            data = payload["content"].encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type",payload["content_type"]+"; charset=utf-8")
            self.send_header("Content-Disposition",'attachment; filename="'+payload["filename"]+'"')
            self.send_header("Content-Length",str(len(data)))
            self.send_header("Cache-Control","no-store")
            self.end_headers()
            self.wfile.write(data)
            return

        routes = {
            '/': lambda : (globals().__setitem__('_RENDERED_VER', UI_BUILD),
                           self._send(200, PAGE_HTML.replace('__UI_VER__', UI_BUILD).encode('utf-8'), 'text/html')),
            '/manifest.webmanifest': lambda : self._send(200, json.dumps({'name': 'VRCX Cloud', 'short_name': 'VRCX', 'start_url': '/', 'display': 'standalone', 'scope': '/', 'background_color': '#eef0f4', 'theme_color': '#6d5ef0', 'icons': [{'src': '/icon-192.png', 'sizes': '192x192', 'type': 'image/png'}, {'src': '/icon-512.png', 'sizes': '512x512', 'type': 'image/png'}]}, ensure_ascii=False).encode('utf-8'), 'application/manifest+json'),
            '/icon-192.png': lambda : self._send(200, _send_icon(192), 'image/png'),
            '/icon-512.png': lambda : self._send(200, _send_icon(512), 'image/png'),
            '/index.html': lambda : (globals().__setitem__('_RENDERED_VER', UI_BUILD),
                                     self._send(200, PAGE_HTML.replace('__UI_VER__', UI_BUILD).encode('utf-8'), 'text/html')),
            '/adapter/health': lambda : self._send(200, {'adapter': 'ok', 'upstream_dist': _find_upstream_dist()}),
        }

        if u.path in routes:
            return routes[u.path]()
        return self._dispatch("GET", u.path, q)

    def do_POST(self):

        cfg = load_config()

        u = urlparse(self.path)

        q = parse_qs(u.query)

        if not self._authed(cfg):

            return self._send(401, {"error": "需要访问口令"})

        # CSRF：浏览器跨站 POST 必带 Origin，同源时 Origin==Host（D-P1-S9）
        origin = self.headers.get("Origin")

        if origin and urlparse(origin).netloc != (self.headers.get("Host") or ""):

            return self._send(403, {"error": "cross-origin blocked"})

        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self.close_connection = True
            return self._send(400, {"error": "invalid content length"})
        if n < 0 or n > 5 * 1024 * 1024:
            self.close_connection = True
            return self._send(413, {"error": "request too large"})
        try:
            body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            return self._send(400, {"error": "invalid JSON"})
        if not isinstance(body, dict):
            return self._send(400, {"error": "JSON object required"})

        return self._dispatch("POST", u.path, q, body)

    def _dispatch(self, method, path, query, body=None):
        try:
            code, payload = ApiRouter(globals(), _RESPONSES, _ensure_scope).dispatch(method, path, query, body)
        except (Exception, SystemExit) as error:
            log(f"web {method} {_log_category(path)}: {type(error).__name__}")
            return self._send(500, {"error": "处理请求失败，请重试"})
        return self._send(code, payload)

def main():

    init_db()

    cfg = load_config()

    proxy = (cfg.get("proxy") or "").strip()

    if proxy:

        vrc_watch.PROXIES = {"http": proxy, "https": proxy}

    threading.Thread(target=_net_sampler, daemon=True).start()

    port = int(cfg.get("web_port") or 8000)

    srv = ThreadingHTTPServer((cfg.get("web_bind") or "0.0.0.0", port), Handler)

    log(f"VRCX Cloud 启动: 局域网访问 http://<服务器地址>:{port}/")

    srv.serve_forever()

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        pass
