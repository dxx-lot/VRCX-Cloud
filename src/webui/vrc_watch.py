#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vrc-watch — VRChat 好友上下线监控，推送到手机/Apple Watch（Bark / Telegram）

用法:
  ./venv/bin/python3 vrc_watch.py auth                # 登录 VRChat（交互式，输入账号/密码/2FA）
  ./venv/bin/python3 vrc_watch.py run                 # 常驻监控（systemd 调用）
  ./venv/bin/python3 vrc_watch.py once                # 拉一次在线好友并打印（测试）
  ./venv/bin/python3 vrc_watch.py push [标题] [内容]   # 手动发一条测试推送
  ./venv/bin/python3 vrc_watch.py history [名字] [天数] # 查看上下线记录（默认最近3天）
"""
import base64
import getpass
import hashlib
import hmac
import json
import tempfile
import os
import queue
import random
import sqlite3
import struct
import sys
import threading
import time
from datetime import datetime
from urllib.parse import quote, urlencode, urlsplit

try:
    import requests
except ImportError:
    print("缺少 requests，请先运行: ./venv/bin/pip install requests")
    sys.exit(1)

from services.presence import PresenceGate, state_of, confirmed_session_start

BASE = "https://api.vrchat.cloud/api/1"
DIR = os.path.abspath(os.environ.get("VRCX_PI_STATE_DIR") or os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(DIR, "config.json")
DB_PATH = os.path.join(DIR, "vrc_watch.db")
# 规范会话存储 = 上游 UI 的登录会话（D-P1-S4 架构翻转）：
# 上游界面登录 → 适配器写入 auth-ui.json；监控与旧界面只读跟随该文件。
# 监控会话过期时不再凭密码后台重登（杜绝突袭验证码邮件），
# 而是等待用户在上游界面重新登录（文件监视自动跟随）。
AUTH_PATH = os.path.join(DIR, "auth-ui.json")

PLATFORM_MAP = {"standalonewindows": "PCVR", "android": "Quest", "ios": "iOS", "web": "网页"}
STATUS_MAP = {"active": "在线", "join me": "Join Me·欢迎加入", "joinme": "Join Me·欢迎加入",
              "ask me": "Ask Me·先询问", "askme": "Ask Me·先询问", "busy": "勿扰"}
SPECIAL_LOCATION = {"": "未知", "offline": "离线", "private": "私密世界", "traveling": "传送中", "local": "本地"}

_world_fail_ts = {}  # 世界名查询失败节流: world_id -> 上次失败时间戳


def parse_location(location):
    """解析 VRChat location 串: wrld_x:123~region(eu)~hidden → (world_id, 实例id, 实例类型)"""
    if not location or location in SPECIAL_LOCATION:
        return None, None, ""
    world_id, _, rest = location.partition(":")
    inst_id = rest.split("~", 1)[0]
    flags = rest[len(inst_id):]
    # 权威映射：上游 locationParser.js（hidden=好友+，friends=仅限好友，
    # invite+canRequestInvite=邀请+，invite=仅限邀请，groupAccessType=群组系）
    if "groupAccessType(plus)" in flags:
        label = "群组+"
    elif "groupAccessType(" in flags or "~group(" in flags:
        label = "群组"
    elif "hidden(" in flags:
        label = "好友+"
    elif "friends(" in flags:
        label = "仅限好友"
    elif "canRequestInvite" in flags:
        label = "邀请+"
    elif "invite(" in flags:
        label = "仅限邀请"
    else:
        label = "公开"
    return world_id, inst_id, label


def trust_rank(tags):
    """信任等级解析——照抄 VRCX computeTrustLevel（2026 版命名）+ 官方默认配色。
    VRChat 已改名: veteran=Trusted User, trusted=Known User, known=User, basic=New User"""
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except ValueError:
            tags = []
    tags = tags or []
    is_troll = "system_troll" in tags or "system_probable_troll" in tags
    is_mod = "admin_moderator" in tags
    if "system_trust_veteran" in tags:
        rank = ("Trusted User", "#b18fff", 5)
    elif "system_trust_trusted" in tags:
        rank = ("Known User", "#ff7b42", 4)
    elif "system_trust_known" in tags:
        rank = ("User", "#2bcf5c", 3)
    elif "system_trust_basic" in tags:
        rank = ("New User", "#1778ff", 2)
    elif "system_trust_legend" in tags:  # 旧版标签兜底
        rank = ("Trusted User", "#b18fff", 5)
    else:
        rank = ("Visitor", "#CCCCCC", 1)
    if is_troll:
        rank = (rank[0] + " · Nuisance", "#782f2f", rank[2])
    elif is_mod:
        rank = (rank[0] + " · Team", "#ff2626", rank[2])
    return rank

PROXIES = None  # 由 config.proxy 生成，VRChat API 与 Telegram 走代理，Bark 直连


def log(msg):
    print(f"[{datetime.now().strftime('%m-%d %H:%M:%S')}] {msg}", flush=True)


def now_ts():
    return int(time.time())


def fmt_ts(ts):
    return datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")


def fmt_duration(sec):
    sec = int(sec)
    if sec < 90:
        return f"{sec}秒"
    m = sec // 60
    if m < 60:
        return f"{m}分钟"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h}小时{m:02d}分"
    d, h = divmod(h, 24)
    return f"{d}天{h}小时"


def ask(prompt):
    try:
        return input(prompt).strip()
    except EOFError:
        raise SystemExit("需要交互输入，请通过 SSH 手动运行该命令")


def totp_now(secret_b32):
    """根据 base32 密钥本地生成 6 位 TOTP 验证码（免装 pyotp）"""
    s = secret_b32.strip().replace(" ", "").upper()
    s += "=" * ((8 - len(s) % 8) % 8)
    key = base64.b32decode(s)
    counter = int(time.time()) // 30
    d = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = d[-1] & 0x0F
    val = (struct.unpack(">I", d[off:off + 4])[0] & 0x7FFFFFFF) % 1000000
    return f"{val:06d}"


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            friend_id TEXT NOT NULL,
            display_name TEXT NOT NULL,
            event TEXT NOT NULL,
            ts INTEGER NOT NULL,
            duration INTEGER,
            world_name TEXT,
            location TEXT,
            status TEXT,
            status_description TEXT,
            platform TEXT
        );
        CREATE TABLE IF NOT EXISTS friends_current (
            friend_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            online_since INTEGER NOT NULL,
            location TEXT,
            world_name TEXT,
            status TEXT,
            status_description TEXT,
            platform TEXT
        );
        CREATE TABLE IF NOT EXISTS worlds (
            world_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            fetched_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS friends_all (
            friend_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            username TEXT,
            tags TEXT,
            last_platform TEXT,
            last_login TEXT,
            updated_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS world_notes (
            world_id TEXT PRIMARY KEY,
            note TEXT,
            updated_at INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_events_friend_ts ON events(friend_id, ts);
        CREATE INDEX IF NOT EXISTS idx_events_ts_id ON events(ts DESC, id DESC);
    """)
    try:
        db.execute("ALTER TABLE events ADD COLUMN previous_location TEXT")
    except sqlite3.OperationalError:
        pass
    try:  # 老库升级：friends_current 增加信任等级 tags 列
        db.execute("ALTER TABLE friends_current ADD COLUMN tags TEXT")
    except sqlite3.OperationalError:
        pass
    try:  # 老库升级：friends_current 增加 state 列（online=游戏内 / active=网页在线）
        db.execute("ALTER TABLE friends_current ADD COLUMN state TEXT")
    except sqlite3.OperationalError:
        pass
    try:  # 老库升级：events 增加 previous 列（状态/简介/位置的旧值）
        db.execute("ALTER TABLE events ADD COLUMN previous TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("ALTER TABLE events ADD COLUMN previous_desc TEXT")
    except sqlite3.OperationalError:
        pass
    try:  # 老库升级：friends_current 增加当前模型列（模型变动检测）
        db.execute("ALTER TABLE friends_current ADD COLUMN avatar TEXT")
    except sqlite3.OperationalError:
        pass
    try:  # 老库升级：friends_all 增加头像列
        db.execute("ALTER TABLE friends_all ADD COLUMN thumb TEXT")
    except sqlite3.OperationalError:
        pass
    try:  
        db.execute("ALTER TABLE events ADD COLUMN prev_state TEXT")
    except sqlite3.OperationalError:
        pass

    try:  
        db.execute("ALTER TABLE friends_all ADD COLUMN in_roster INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass
    try:  # 老库升级：friends_all 增加最后活动列
        db.execute("ALTER TABLE friends_all ADD COLUMN last_activity TEXT")
    except sqlite3.OperationalError:
        pass
    db.commit()
    return db


class AuthExpired(Exception):
    pass


class _RateLimitedSession(requests.Session):
    '全局限速：对 api.vrchat.cloud 的调用保持最小间隔，\n    避免 Pi 与同 IP 的 VRCX 一起被 VRChat 限流。'

    MIN_INTERVAL = 0.4
    _last_call = 0.0
    _lock = threading.Lock()

    def request(self, method, url, **kw):
        cls = type(self)
        with cls._lock:
            wait = cls.MIN_INTERVAL - (time.time() - cls._last_call)
            if wait > 0:
                time.sleep(wait)
            cls._last_call = time.time()
        return super().request(method, url, **kw)


class TwoFactorRequired(Exception):
    """登录需要两步验证（kinds: ['totp'] 或 ['otp']），由调用方决定如何获取验证码"""

    def __init__(self, kinds):
        super().__init__(kinds)
        self.kinds = kinds


def _ws_proxy_kw():
    'websocket.connect 的代理 kwarg：与 REST 共用 config.proxy 开关。\n    注意：websocket-client 1.9 的 proxy=URL 参数是坏的（proxy_info 只认\n    http_proxy_host/proxy_type 老式键，proxy 键被 **options 静默吞掉→静默直连，\n    socks5h 由 _http.py 原生路由到 python-socks（DNS 走代理侧）。'




    if not PROXIES:
        return {}
    url = PROXIES.get("https") or PROXIES.get("http")
    if not url:
        return {}
    u = urlsplit(url)
    kw = {"proxy_type": (u.scheme or "http").lower(),
          "http_proxy_host": u.hostname,
          "http_proxy_port": u.port or (1080 if u.scheme.startswith("socks") else 80)}
    if u.username:
        kw["http_proxy_auth"] = (u.username, u.password or "")
    return kw


WS_URL = "wss://pipeline.vrchat.cloud"
REFRESH_FILE = os.path.join(DIR, ".refresh")


def _refresh_ts():
    try:
        return os.path.getmtime(REFRESH_FILE)
    except OSError:
        return 0


def _poll_delay(poll):
    '轮询抖动 ±15%：反机器人启发式抓的就是秒表级规律间隔'
    return max(1.0, poll * random.uniform(0.85, 1.15))



def _wait_wake_or_refresh(wake, poll, last_seen):
    """等待期间响应三件事: WS 好友事件(立即) / 网页端手动刷新(.refresh 文件, ≤1秒) / 普通超时。
    返回: -1=事件触发(需去抖) / 新的 refresh 时间戳(手动刷新) / 原值=普通超时"""
    deadline = time.time() + poll
    while time.time() < deadline:
        if wake.is_set():
            wake.clear()
            return -1
        try:
            ts = os.path.getmtime(REFRESH_FILE)
        except OSError:
            ts = 0
        if ts > last_seen and time.time() - ts < 120:
            return ts
        time.sleep(1)
    wake.clear()
    return last_seen


def ws_pipeline_thread(client_box, wake, ws_queue):
    '。'

    import websocket  # websocket-client
    here = os.path.dirname(os.path.abspath(__file__))
    
    # 其次仓库形态 src/webui/../../backend/
    for cand in (os.path.join(here, "domain"), os.path.normpath(os.path.join(here, "..", "..", "backend")), here):
        if os.path.exists(os.path.join(cand, "ws_events.py")):
            if cand not in sys.path:
                sys.path.insert(0, cand)
            break
    from ws_events import ReconnectPolicy
    policy = ReconnectPolicy()
    while True:
        try:
            client = client_box["c"]
            r = client.s.get(f"{BASE}/auth", timeout=20)
            token = (r.json() or {}).get("token")
            if not token:
                log("WS: 未获取到 auth token，60 秒后重试")
                time.sleep(60)
                continue
            cookie = "; ".join(f"{c.name}={c.value}" for c in client.s.cookies)
            ws = websocket.WebSocket()
            # WS 与 REST 走同一代理开关（config.proxy；relay 隧道 socks5h 由
            # websocket-client 原生支持，DNS 一并在代理侧解析——_http.py socks5h 分支）
            ws.connect(f"{WS_URL}/?auth={token}",
                       header=[f"Cookie: {cookie}", "User-Agent: VRCX/2026.09.16"],
                       timeout=15, **_ws_proxy_kw())
            policy.next_delay(after_success=True)   
            log("✅ 实时管线已连接（WebSocket，VRCX 同款）——好友变化秒级触达")
            wake.set()
            ws.settimeout(30)
            while True:
                try:
                    raw = ws.recv()
                except websocket.WebSocketTimeoutException:
                    try:
                        ws.ping()  # 空闲保活
                    except Exception:
                        raise
                    continue
                try:
                    j = json.loads(raw)
                except ValueError:
                    continue
                t = j.get("type", "")
                content = j.get("content")
                if isinstance(content, str):
                    try:
                        content = json.loads(content)
                    except ValueError:
                        content = None
                if not isinstance(content, dict):
                    continue
                uid = content.get("userId") or (content.get("user") or {}).get("id")
                if t == "friend-offline":
                    if uid:
                        ws_queue.put({"fid": uid, "_remove": True, "_kind": "offline"})
                        wake.set()
                elif t == "friend-delete":
                    if uid:
                        ws_queue.put({"fid": uid, "_remove": True, "_kind": "delete",
                                      "name": (content.get("user") or {}).get("displayName") or ""})
                        wake.set()
                elif t in ("friend-online", "friend-active", "friend-location",
                           "friend-update", "friend-add"):
                    u = content.get("user") or {}
                    if not uid:
                        continue
                    snap = {"fid": uid,
                            "name": u.get("displayName"),
                            "status": u.get("status"),
                            "desc": u.get("statusDescription"),
                            "avatar": u.get("currentAvatarImageUrl"),
                            "platform": (content.get("platform") or "").lower(),
                            "tags": u.get("tags")}
                    if t in ("friend-online", "friend-location"):
                        snap["state"] = "online"     # 上游: location 强制 online (JANK)
                        snap["location"] = content.get("location") or u.get("location") or ""
                    elif t == "friend-active":
                        snap["state"] = "active"
                        snap["location"] = "offline"
                    elif t == "friend-add":
                        snap["state"] = "active"
                        snap["location"] = "offline"
                        snap["_kind"] = "add"
                    else:                              # friend-update: 只更新字段
                        snap["state"] = None
                        snap["location"] = None
                    ws_queue.put(snap)
                    wake.set()
        except AuthExpired:
            log("WS: 登录过期，等待主流程重新登录")
            time.sleep(60)
        except Exception as e:
            delay = policy.next_delay(after_success=False)   
            log(f"WebSocket 断开: {type(e).__name__} · {delay:.0f} 秒后重连")
            time.sleep(delay)

class VRChatClient:
    def __init__(self, cfg):
        self.cfg = cfg
        self.s = _RateLimitedSession()
        self.s.headers["User-Agent"] = cfg.get("user_agent") or "vrc-friend-watch/1.0 (personal friend status monitor)"
        if PROXIES:
            self.s.proxies = PROXIES
        self.creds = None
        self.last_login_ts = 0  # 上次真正用账号密码登录的时间（VRChat 有会话数上限，重登要节流）
        self.pending_kinds = None  # 两步验证的类型（totp/emailOtp/otp），第二次调用时复用
        self._load_cookies()

    # ---------- 登录 ----------
    def _load_cookies(self):
        if not os.path.exists(AUTH_PATH):
            return
        try:
            with open(AUTH_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.get("cookies", {}).items():
                self.s.cookies.set(k, v, domain="api.vrchat.cloud")
            self.creds = data.get("credentials")
        except Exception as e:
            log(f"读取 auth.json 失败: {e}")

    def _save_cookies(self, path=None):
        data = {"cookies": {c.name: c.value for c in self.s.cookies}, "saved_at": now_ts()}
        if self.creds:
            data["credentials"] = self.creds
        target = path or AUTH_PATH
        fd, temporary = tempfile.mkstemp(prefix=".auth-", dir=os.path.dirname(target))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _json(r):
        try:
            return r.json()
        except ValueError:
            raise SystemExit(f"接口返回异常 HTTP {r.status_code}: {r.text[:200]}")

    def is_logged_in(self):
        try:
            response = self.s.get(f"{BASE}/auth/user", timeout=20)
            value = response.json() if response.status_code == 200 else None
            return isinstance(value, dict) and bool(value.get('id')) and not value.get('requiresTwoFactorAuth')
        except (requests.RequestException, ValueError) as e:
            log(f"检查登录状态网络错误: {e}")
            return False

    def _set_basic(self, username, password):
        """构造 VRChat 要求的 Basic 头: base64(urlencode(用户名):urlencode(密码))"""
        token = base64.b64encode(
            f"{quote(username, safe='')}:{quote(password, safe='')}".encode("utf-8")
        ).decode("ascii")
        self.s.headers["Authorization"] = f"Basic {token}"

    def _clear_basic(self):
        self.s.headers.pop("Authorization", None)

    def login(self, username, password, totp_code=None, totp_secret=None,
              store_creds=False, kinds=None):
        # 旧 POST /auth/login 已被 VRChat 下线(404)，现行方式是 Basic 认证调 GET /auth/user。
        # 两步验证分两次调用：第一次只发账号密码（触发邮件/挑战，返回 TwoFactorRequired），
        # 第二次带验证码 + kinds——此时绝不能重新 Basic 登录，否则会生成新会话/新邮件，
        # 导致用户手里这封验证码对不上号。
        if not totp_code:
            # 上游 login()/resendEmail2fa 每次发起密码挑战前必先 clearCookies（auth.js:540/225）。
            # 带着遗留 twoFactorAuth cookie 发挑战，VRChat 视同该会话验证码已发过、
            
            self.s.cookies.clear()
            self._set_basic(username, password)
            try:
                r = self.s.get(f"{BASE}/auth/user", timeout=25)
            finally:
                self._clear_basic()
            j = self._json(r)
            if r.status_code == 200 and j.get("id"):
                return self._finish_login(username, password, totp_secret, store_creds)
            kinds = j.get("requiresTwoFactorAuth") or []
            if not kinds:
                err = j.get("error")
                msg = err.get("message") if isinstance(err, dict) else None
                raise SystemExit(msg or f"登录失败: {json.dumps(j, ensure_ascii=False)[:200]}")
            if "totp" in kinds and totp_secret:
                totp_code = totp_now(totp_secret)      # 存了 TOTP 密钥就自动生成并继续验证
            else:
                self.pending_kinds = list(kinds)
                raise TwoFactorRequired(kinds)

        # 带验证码：在挂起会话上直接验证（保持 cookie 不动）
        kinds = kinds or self.pending_kinds or ["totp"]
        if "emailOtp" in kinds:
            endpoint, what = f"{BASE}/auth/twofactorauth/emailotp/verify", "邮箱验证码"
        elif "otp" in kinds and "totp" not in kinds:
            endpoint, what = f"{BASE}/auth/twofactorauth/otp/verify", "恢复代码"
        else:
            endpoint, what = f"{BASE}/auth/twofactorauth/totp/verify", "2FA验证码"
        r2 = self.s.post(endpoint, json={"code": totp_code}, timeout=25)
        if not self._json(r2).get("verified"):
            raise SystemExit(f"{what}验证失败，代码错误或已过期")
        r3 = self.s.get(f"{BASE}/auth/user", timeout=25)
        if r3.status_code != 200:
            raise SystemExit("2FA 验证后仍无法获取用户信息")
        self._finish_login(username, password, totp_secret, store_creds)

    def _finish_login(self, username, password, totp_secret, store_creds):
        self.pending_kinds = None
        self.creds = {"username": username, "password": password} if store_creds else None
        if totp_secret and self.creds is not None:
            self.creds["totp_secret"] = totp_secret
        self.last_login_ts = now_ts()
        self._save_cookies()
        log("✅ VRChat 登录成功，凭据已保存到 auth.json(600权限)")

    def try_relogin(self):
        # The monitor follows the UI session. Stored credentials never authorize
        # a background password challenge (which can send another email).
        return False

    # ---------- 数据 ----------
    def get_favorite_friend_ids(self):
        """收藏夹里的好友 id 列表（VRChat favorites, type=friend）"""
        r = self.s.get(f"{BASE}/favorites", params={"type": "friend"}, timeout=20)
        if r.status_code == 401:
            raise AuthExpired()
        r.raise_for_status()
        return [f.get("favoriteId") for f in r.json()
                if f.get("type") == "friend" and f.get("favoriteId")]

    def get_friends(self, offline=False):
        friends, offset = [], 0
        while True:
            params = {"n": 100, "offset": offset}
            if offline:
                params["offline"] = "true"
            r = self.s.get(f"{BASE}/auth/user/friends",
                           params=params, timeout=25)
            if r.status_code == 401:
                raise AuthExpired()
            if r.status_code == 429:
                raise requests.HTTPError("429 被限流")
            r.raise_for_status()
            batch = r.json()
            friends.extend(batch)
            if len(batch) < 100:
                return friends
            offset += 100

    def get_world_name(self, world_id, db, cache_only=False):
        if not world_id:
            return None
        row = db.execute("SELECT name, fetched_at FROM worlds WHERE world_id=?",
                         (world_id,)).fetchone()
        if row and now_ts() - row[1] < 30 * 86400:
            return row[0]
        if cache_only:
            return row[0] if row else None
        if now_ts() - _world_fail_ts.get(world_id, 0) < 600:
            return row[0] if row else world_id
        try:
            r = self.s.get(f"{BASE}/worlds/{world_id}", timeout=25)
            if r.status_code == 200:
                name = r.json().get("name") or world_id
                db.execute("INSERT OR REPLACE INTO worlds VALUES (?,?,?)",
                           (world_id, name, now_ts()))
                db.commit()
                return name
            _world_fail_ts[world_id] = now_ts()
            log(f"获取世界 {world_id} 失败 HTTP {r.status_code}")
        except requests.RequestException as e:
            _world_fail_ts[world_id] = now_ts()
            log(f"获取世界 {world_id} 失败: {e}")
        return row[0] if row else world_id


# ---------- 推送 ----------
def send_bark(bcfg, title, body):
    key = (bcfg.get("key") or "").strip()
    if not key or key.startswith("把你的"):
        log("⚠️ config.json 里还没填 Bark key，跳过推送")
        return False
    server = (bcfg.get("server") or "https://api.day.app").rstrip("/")
    params = {"group": bcfg.get("group") or "vrc", "isArchive": 1}
    level = bcfg.get("level") or "timeSensitive"
    params["level"] = level
    if level == "critical":
        params["volume"] = str(bcfg.get("critical_volume", 10))
    if bcfg.get("sound"):
        params["sound"] = bcfg["sound"]
    url = f"{server}/{quote(key, safe='')}/{quote(title)}/{quote(body)}?{urlencode(params)}"
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "vrc-friend-watch/1.0"})
        log(f"Bark 推送 HTTP {r.status_code}: {title}")
        return r.status_code == 200
    except requests.RequestException as e:
        log(f"Bark 推送失败: {e}")
        return False


def send_telegram(tcfg, title, body):
    token = (tcfg.get("bot_token") or "").strip()
    chat_id = str(tcfg.get("chat_id") or "").strip()
    if not token or not chat_id:
        log("⚠️ Telegram 未配置完整(bot_token/chat_id)，跳过推送")
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat_id, "text": f"{title}\n{body}"},
                          timeout=15, proxies=PROXIES)
        log(f"Telegram 推送 HTTP {r.status_code}: {title}")
        return r.status_code == 200
    except requests.RequestException as e:
        log(f"Telegram 推送失败: {e}")
        return False


def push(cfg, title, body):
    
    if cfg.get("push_enabled", True) is False:
        return False
    ok = False
    if cfg.get("bark", {}).get("enabled", True):
        ok = send_bark(cfg["bark"], title, body) or ok
    if cfg.get("telegram", {}).get("enabled", False):
        ok = send_telegram(cfg["telegram"], title, body) or ok
    return ok


# ---------- 展示 ----------
def describe(snap, world_name):
    loc = snap["location"]
    world_id, _, label = parse_location(loc)
    world = SPECIAL_LOCATION.get(loc) or world_name or world_id or "未知"
    status = STATUS_MAP.get(snap["status"]) or snap["status"] or "在线"
    plat = PLATFORM_MAP.get(snap["platform"], snap["platform"]) or "未知平台"
    parts = [f"世界: {world}"]
    if label:
        parts.append(f"实例: {label}")
    if snap["desc"]:
        parts.append(f"签名: {snap['desc']}")
    parts.append(f"状态: {status}")
    parts.append(f"平台: {plat}")
    return " | ".join(parts)


# ---------- 常驻监控 ----------
def watch(cfg, db):
    gate = PresenceGate(max(0, int(cfg.get("presence_grace_seconds", 30))))
    prev = {}
    for fid, name, since in db.execute(
            "SELECT friend_id, display_name, online_since FROM friends_current"):
        prev[fid] = {"name": name, "online_since": since}
    prev_loc = {}
    for fid, loc in db.execute("SELECT friend_id, location FROM friends_current"):
        prev_loc[fid] = loc or ""
    prev_state = {}    # 上一轮状态: online(游戏内) / active(网页在线)
    prev_status = {}   # 上一轮 status（Join Me 等）
    prev_desc = {}     # 上一轮状态签名
    prev_avatar = {}   # 上一轮当前模型（模型变动检测）
    prev_tags = {}     # 上一轮 tags（等级变动检测）
    for fid, loc, st, statu, desc, av in db.execute(
            "SELECT friend_id, location, state, status, status_description, avatar "
            "FROM friends_current"):
        prev_state[fid] = st or ("online" if (loc or "").startswith("wrld_") else "active")
        prev_status[fid] = statu or ""
        prev_desc[fid] = desc or ""
        prev_avatar[fid] = av or ""
    for fid, tg in db.execute("SELECT friend_id, tags FROM friends_current"):
        prev_tags[fid] = tg or ""
    fav_ids = set()      # VRChat 收藏夹里的好友 id（推送名单的自动来源）
    last_fav_sig = None
    next_fav_sync = 0
    next_offline_sync = 0  # 启动后第一轮就同步完整好友列表
    reconciled = False  # 每次启动后第一轮只静默对账，防止重启/停机期间积压的重复推送
    auth_mtime = os.path.getmtime(AUTH_PATH) if os.path.exists(AUTH_PATH) else 0
    client = VRChatClient(cfg)
    wake = threading.Event()
    ws_queue = queue.Queue()
    client_box = {"c": client}
    threading.Thread(target=ws_pipeline_thread, args=(client_box, wake, ws_queue), daemon=True).start()
    poll = max(15, int(cfg.get("poll_seconds", 30)))
    log(f"vrc-watch 启动: 轮询间隔 {poll}s, 数据库在线记录 {len(prev)} 条")

    last_auth_notify = 0
    last_refresh_seen = [_refresh_ts()]  # 网页端手动刷新的触发文件时间戳
    while True:
        cfg = load_config()  # 配置热更新（Bark key / watch_list / 间隔改完即生效）
        poll = max(15, int(cfg.get("poll_seconds", 30)))
        manual_watch = [w.lower() for w in cfg.get("watch_list") or []]

        def watched(name, fid=None):
            if not watch_enabled:
                return True
            if fid and fid in watch_set:
                return True
            return name.lower() in watch_set

        if os.path.exists(AUTH_PATH):
            m = os.path.getmtime(AUTH_PATH)
            if m != auth_mtime:
                auth_mtime = m
                client = VRChatClient(cfg)
                client_box["c"] = client
                log("检测到新的登录凭据，重新加载")

        if not os.path.exists(AUTH_PATH):
            if now_ts() - last_auth_notify > 3600:
                push(cfg, "⏳ vrc-watch 等待登录",
                     "请打开网页中的账号页完成登录。")
                last_auth_notify = now_ts()
            log("未登录，等待 vrc_watch.py auth 完成…")
            time.sleep(30)
            continue

        try:
            friends = client.get_friends()
        except AuthExpired:
            log("登录已过期(401)")
            if now_ts() - last_auth_notify > 3600:
                push(cfg, "⚠️ vrc-watch 登录过期", "请在账号页面重新登录")
                last_auth_notify = now_ts()
            log("等待账号页面重新登录，不发起后台密码重登")
            time.sleep(60)
            continue
        except requests.RequestException as e:
            log(f"网络错误: {e}")
            time.sleep(poll * 2)
            continue

        now = now_ts()
        db.execute("INSERT OR REPLACE INTO meta VALUES ('last_sync', ?)", (str(now),))

        # 关注名单 = VRChat 收藏夹（自动跟随增删）+ config.watch_list 手动补充
        if not cfg.get("watch_favorites", True):
            fav_ids = set()
        elif now >= next_fav_sync:
            next_fav_sync = now + max(20, int(cfg.get("favorites_sync_seconds", 90)))
            try:
                ids = client.get_favorite_friend_ids()
                fav_ids = set(ids)
                sig = ",".join(sorted(ids))
                if sig != last_fav_sig:
                    last_fav_sig = sig
                    by_id = {f.get("id"): f.get("displayName") for f in friends}
                    names = []
                    for uid in ids:
                        nm = by_id.get(uid)
                        if not nm:
                            row = db.execute("SELECT display_name FROM friends_all "
                                             "WHERE friend_id=?", (uid,)).fetchone()
                            nm = row[0] if row else uid
                        names.append(nm)
                    db.execute("INSERT OR REPLACE INTO meta VALUES ('watch_source', ?)",
                               (json.dumps({"count": len(ids), "names": names, "ids": ids,
                                            "ts": now}, ensure_ascii=False),))
                    db.commit()
                    shown = "、".join(names[:5]) + ("…" if len(names) > 5 else "")
                    log(f"收藏好友名单已同步: {len(ids)} 人（{shown}）")
            except (AuthExpired, requests.RequestException) as e:
                next_fav_sync = now + 30
                log(f"收藏好友名单同步失败，稍后重试: {e}")
        watch_set = set(manual_watch) | fav_ids
        watch_enabled = bool(manual_watch) or bool(fav_ids) or cfg.get("watch_favorites", True)

        cur = {}
        for f in friends:
            name = f.get("displayName") or f.get("username") or "?"
            loc_raw = f.get("location") or ""
            state = state_of(f)
            if not f.get('id') or state == 'offline':
                continue
            cur[f.get("id")] = {
                "name": name,
                "state": state,
                "location": loc_raw,
                "avatar": f.get("currentAvatarImageUrl") or "",
                "status": f.get("status") or "",
                "desc": f.get("statusDescription") or "",
                "platform": (f.get("last_platform") or "").lower(),
                "tags": f.get("tags") or [],
            }

        # 应用 WS 事件（VRCX 同款：事件即权威状态，立即生效，不等轮询）
        ws_updates = {}
        try:
            while True:
                item = ws_queue.get_nowait()
                # A websocket batch may contain location, status and avatar
                # messages for the same user. Keep all partial fields in order.
                earlier = ws_updates.get(item['fid'], {})
                if item.get('_remove') or item.get('_kind') == 'delete':
                    ws_updates[item['fid']] = item
                else:
                    if item.get('state') in ('online','active'):
                        earlier = {k:v for k,v in earlier.items() if k not in ('_remove','_kind')}
                    ws_updates[item['fid']] = dict(earlier, **item)
        except queue.Empty:
            pass
        for fid, ws in ws_updates.items():
            if ws.get("_kind") == "delete":
                # 好友日志：删除好友（VRCX FriendLog/Unfriend）
                nm = ws.get("name") or ""
                row = db.execute("SELECT display_name FROM friends_all WHERE friend_id=?", (fid,)).fetchone()
                nm = nm or (row[0] if row else fid)
                db.execute("INSERT INTO events (friend_id,display_name,event,ts) VALUES (?,?,?,?)",
                           (fid, nm, "friend-delete", now))
                db.execute("UPDATE friends_all SET in_roster=0 WHERE friend_id=?", (fid,))
                cur.pop(fid, None)
                gate.forget(fid)
                log(f"👥 {nm} 删除好友（资料留档）")
                continue
            if ws.get("_kind") == "add":
                # 好友日志：新的好友（VRCX FriendLog/Friend）
                db.execute("INSERT INTO events (friend_id,display_name,event,ts) VALUES (?,?,?,?)",
                           (fid, ws.get("name") or fid, "friend-add", now))
                next_offline_sync = 0  # 立即同步好友列表
                log(f"👥 {ws.get('name') or fid} 新的好友")
            if ws.get("_remove"):
                cur.pop(fid, None)  # friend-offline → 移除，触发下线转换
                continue
            ex = cur.get(fid)
            if ex is None:
                if ws.get("state") in ("online", "active"):
                    cur[fid] = {"name": ws.get("name") or fid, "state": ws["state"],
                                "location": ws.get("location") or ("offline" if ws["state"] == "active" else ""),
                                "avatar": ws.get("avatar") or "", "status": ws.get("status") or "",
                                "desc": ws.get("desc") or "", "platform": ws.get("platform") or "",
                                "tags": ws.get("tags") or []}
            else:
                if ws.get("state"):
                    ex["state"] = ws["state"]
                    if ws.get("location") is not None:
                        ex["location"] = ws["location"]
                    elif ws["state"] == "active":
                        ex["location"] = "offline"
                for k in ("status", "desc", "avatar"):
                    if ws.get(k) is not None:
                        ex[k] = ws[k]
                if ws.get("platform"):
                    ex["platform"] = ws["platform"]
                if ws.get("tags"):
                    ex["tags"] = ws["tags"]

        cur = gate.apply(cur, now)

        if not reconciled:
            for fid, snap in cur.items():
                if fid in prev:
                    if prev_state.get(fid) != snap["state"]: prev[fid]["online_since"] = now
                    else:
                        prev[fid]["online_since"] = confirmed_session_start(db, fid, snap["state"], prev[fid]["online_since"], now)
                    prev[fid]["name"] = snap["name"]
                else:
                    prev[fid] = {"name": snap["name"], "online_since": now}
                prev_loc[fid] = snap["location"]
                prev_state[fid] = snap["state"]
                prev_status[fid] = snap["status"]
                prev_desc[fid] = snap["desc"]
                prev_avatar[fid] = snap["avatar"]
                prev_tags[fid] = json.dumps(snap["tags"], ensure_ascii=False) if snap.get("tags") else None
            for fid, info in list(prev.items()):
                if fid not in cur:
                    last_loc = prev_loc.get(fid, "")
                    last_wid = last_loc.split(":")[0] if last_loc and last_loc not in SPECIAL_LOCATION else None
                    last_world = client.get_world_name(last_wid, db, cache_only=True) if last_wid else None
                    db.execute("INSERT INTO events (friend_id,display_name,event,ts,duration,"
                               "world_name,location,prev_state) VALUES (?,?,?,?,?,?,?,?)",
                               (fid, info["name"], "offline", now, None, last_world, last_loc, prev_state.get(fid)))
                    db.execute("DELETE FROM friends_current WHERE friend_id=?", (fid,))
                    del prev[fid]
            for fid, snap in cur.items():
                db.execute("INSERT OR REPLACE INTO friends_current VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                           (fid,snap['name'],prev[fid]['online_since'],snap['location'],
                            client.get_world_name(snap['location'].split(':')[0],db,cache_only=True) if snap['location'].startswith('wrld_') else None,
                            snap['status'],snap['desc'],snap['platform'],json.dumps(snap['tags'],ensure_ascii=False),snap['state'],snap['avatar']))
            reconciled = True
            db.commit()
            log(f"首次同步完成: {len(cur)} 位好友在线（本次不推送）")
            wake.wait(poll)
            wake.clear()
            continue

        # 上线/网页在线/状态/简介/位置变化：全员记录进数据库，仅收藏好友触发上线/下线推送
        for fid, snap in cur.items():
            new_state = snap["state"]
            if fid not in prev:
                # 本轮新出现（上一轮离线）→ 真实上线
                loc = snap["location"]
                world_id = loc.split(":")[0] if loc.startswith("wrld_") else None
                world_name = client.get_world_name(world_id, db) if world_id else None
                prev[fid] = {"name": snap["name"], "online_since": now}
                prev_state[fid] = new_state
                if new_state == "active":
                    if watched(snap["name"], fid) and cfg.get("notify_active", True):
                        push(cfg, f"🌐 {snap['name']} 网页在线上线", "登录网页端，未进世界")
                    db.execute("INSERT INTO events (friend_id,display_name,event,ts,location,"
                               "status,status_description,platform) VALUES (?,?,?,?,?,?,?,?)",
                               (fid, snap["name"], "active", now, loc,
                                snap["status"], snap["desc"], snap["platform"]))
                    log(f"🌐 {snap['name']} 网页在线")
                else:
                    body = describe(snap, world_name)
                    if watched(snap["name"], fid) and cfg.get("notify_online", True):
                        push(cfg, f"🟢 {snap['name']} 上线了", body)
                    db.execute("INSERT INTO events (friend_id,display_name,event,ts,world_name,"
                               "location,status,status_description,platform) VALUES (?,?,?,?,?,?,?,?,?)",
                               (fid, snap["name"], "online", now, world_name, loc,
                                snap["status"], snap["desc"], snap["platform"]))
                    log(f"🟢 {snap['name']} 上线 | {body}")
            else:
                old_state = prev_state.get(fid, "online")
                if old_state != new_state:
                    prev_state[fid] = new_state
                    started = prev[fid]['online_since']
                    prev[fid]['online_since'] = now
                    if new_state == "active":
                        # 游戏内 → 回大厅/网页在线（记录离开的世界）
                        left_wid = (prev_loc.get(fid) or "").split(":")[0]
                        left_world = client.get_world_name(left_wid, db, cache_only=True) \
                            if left_wid and left_wid.startswith("wrld_") else None
                        # End the game session even if the website remains online.
                        db.execute("INSERT INTO events (friend_id,display_name,event,ts,duration,world_name,location,prev_state) VALUES (?,?,?,?,?,?,?,?)",
                                   (fid,snap['name'],'offline',now,max(0,now-started),left_world,prev_loc.get(fid),'online'))
                        if watched(snap['name'],fid) and cfg.get('notify_offline',True):
                            push(cfg,f"🔴 {snap['name']} 下线了",f"在线 {fmt_duration(max(0,now-started))} · {left_world or '未知'}")
                        db.execute("INSERT INTO events (friend_id,display_name,event,ts,"
                                   "status,status_description,platform,previous,prev_state) "
                                   "VALUES (?,?,?,?,?,?,?,?,?)",
                                   (fid, snap["name"], "active", now,
                                    snap["status"], snap["desc"], snap["platform"], left_world, "online"))
                        if watched(snap["name"], fid) and cfg.get("notify_active", True):
                            push(cfg, f"🌐 {snap['name']} 网页在线",
                                 f"离开世界: {left_world or '未知'}")
                        log(f"🌐 {snap['name']} 回到大厅（网页在线）")
                    else:
                        # 大厅/网页 → 进入世界
                        loc = snap["location"]
                        world_id = None if loc in SPECIAL_LOCATION else loc.split(":")[0]
                        world_name = client.get_world_name(world_id, db) if world_id else None
                        db.execute("INSERT INTO events (friend_id,display_name,event,ts,world_name,"
                                   "location,status,status_description,platform) VALUES (?,?,?,?,?,?,?,?,?)",
                                   (fid, snap["name"], "online", now, world_name, loc,
                                    snap["status"], snap["desc"], snap["platform"]))
                        if watched(snap["name"], fid) and cfg.get("notify_online", True):
                            push(cfg, f"🟢 {snap['name']} 进入世界",
                                 f"{world_name or '未知世界'} · 来自网页端/大厅")
                        log(f"🎮 {snap['name']} 进入世界 {world_name or world_id}")
            # 状态变动（Join Me / Ask Me / 勿扰 / 在线 互切，VRCX 式记录旧值）
            if fid in prev_status and prev_status[fid] != snap["status"]:
                old_l = STATUS_MAP.get(prev_status[fid], prev_status[fid] or "无")
                new_l = STATUS_MAP.get(snap["status"], snap["status"] or "无")
                db.execute("INSERT INTO events (friend_id,display_name,event,ts,status,"
                           "status_description,platform,previous,previous_desc) "
                           "VALUES (?,?,?,?,?,?,?,?,?)",
                           (fid, snap["name"], "status", now, snap["status"],
                            snap["desc"], snap["platform"],
                            prev_status[fid], prev_desc.get(fid, "")))
                if watched(snap["name"], fid) and cfg.get("notify_status", False):
                    push(cfg, f"🔄 {snap['name']} 状态变动", f"{old_l} → {new_l}")
                log(f"🔄 {snap['name']} 状态变动: {old_l} → {new_l}")
            # 简介变更
            if fid in prev_desc and prev_desc[fid] != snap["desc"]:
                db.execute("INSERT INTO events (friend_id,display_name,event,ts,"
                           "status_description,platform,previous) VALUES (?,?,?,?,?,?,?)",
                           (fid, snap["name"], "desc", now, snap["desc"], snap["platform"],
                            prev_desc[fid]))
                if watched(snap["name"], fid) and cfg.get("notify_desc", False):
                    push(cfg, f"✏️ {snap['name']} 简介变更",
                         f"{(prev_desc[fid] or '无')[:40]} → {(snap['desc'] or '无')[:40]}")
                log(f"✏️ {snap['name']} 简介变更: {snap['desc'][:40]}")
            prev_status[fid] = snap["status"]
            prev_desc[fid] = snap["desc"]
            # 模型变动（VRCX「模型变动」动态的 API 版：好友当前模型 URL 变化）
            old_av = prev_avatar.get(fid)
            if old_av and snap["avatar"] and old_av != snap["avatar"]:
                db.execute("INSERT INTO events (friend_id,display_name,event,ts,"
                           "location,platform,previous) VALUES (?,?,?,?,?,?,?)",
                           (fid, snap["name"], "avatar", now, snap["avatar"],
                            snap["platform"], old_av))
                if watched(snap["name"], fid) and cfg.get("notify_avatar", False):
                    push(cfg, f"👕 {snap['name']} 模型变动", "展开动态可查看前后模型")
                log(f"👕 {snap['name']} 模型变动")
            prev_avatar[fid] = snap["avatar"]
            # 昵称变动（VRCX FriendLog/DisplayName）
            old_nm = prev[fid]["name"]
            if old_nm and old_nm != snap["name"]:
                db.execute("INSERT INTO events (friend_id,display_name,event,ts,previous) "
                           "VALUES (?,?,?,?,?)", (fid, snap["name"], "name", now, old_nm))
                log(f"📛 {snap['name']} 昵称变动: {old_nm} → {snap['name']}")
                prev[fid]["name"] = snap["name"]
            # 等级变动（VRCX FriendLog/TrustLevel）
            old_rank = trust_rank(prev_tags.get(fid))[0] if prev_tags.get(fid) else ""
            new_rank = trust_rank(snap["tags"])[0]
            if old_rank and old_rank != new_rank:
                db.execute("INSERT INTO events (friend_id,display_name,event,ts,"
                           "status_description,previous) VALUES (?,?,?,?,?,?)",
                           (fid, snap["name"], "trust", now, f"({old_rank} → {new_rank})",
                            old_rank))
                log(f"📈 {snap['name']} 等级变动: {old_rank} → {new_rank}")
            prev_tags[fid] = json.dumps(snap["tags"], ensure_ascii=False) if snap.get("tags") else None
            # 位置变化（仅游戏内有效）
            loc = snap["location"]
            old_loc = prev_loc.get(fid)
            # 上游对任意位置变化都记 GPS（含进入私人房间，world_name 留空显示"位于私人房间"）
            if (old_loc is not None and old_loc != loc
                    and old_loc not in ("", "offline") and loc not in ("", "offline", "traveling")):
                world_id = loc.split(":")[0] if loc.startswith("wrld_") else None
                world_name = client.get_world_name(world_id, db) if world_id else None
                label = parse_location(loc)[2]
                body = f"{world_name or SPECIAL_LOCATION.get(loc) or world_id or '未知'}（{label}）"
                db.execute("INSERT INTO events (friend_id,display_name,event,ts,world_name,"
                           "location,status,status_description,platform,previous_location,previous) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                           (fid,snap['name'],'location',now,world_name,loc,snap['status'],snap['desc'],snap['platform'],old_loc,
                            client.get_world_name(old_loc.split(':')[0],db,cache_only=True) if old_loc.startswith('wrld_') else SPECIAL_LOCATION.get(old_loc)))
                if watched(snap["name"], fid) and cfg.get("notify_world_change"):
                    push(cfg, f"🌍 {snap['name']} 前往了新世界", body)
                log(f"🌍 {snap['name']} → {body}")
            prev_loc[fid] = loc
            cached = (client.get_world_name(loc.split(":")[0], db)
                      if loc.startswith("wrld_") else None)
            tags = json.dumps(snap["tags"], ensure_ascii=False) if snap.get("tags") else None
            db.execute("INSERT OR REPLACE INTO friends_current VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (fid, snap["name"], prev[fid]["online_since"], loc, cached,
                        snap["status"], snap["desc"], snap["platform"], tags, new_state,
                        snap["avatar"]))

        # 下线：全员记录，仅收藏好友推送（带最后所在位置）
        for fid in list(prev.keys()):
            if fid not in cur:
                info = prev.pop(fid)
                
                was_active = prev_state.get(fid) == "active"
                prev_state.pop(fid, None)
                prev_status.pop(fid, None)
                prev_desc.pop(fid, None)
                prev_tags.pop(fid, None)
                prev_avatar.pop(fid, None)
                last_loc = prev_loc.pop(fid, "")
                db.execute("DELETE FROM friends_current WHERE friend_id=?", (fid,))
                dur = now - info["online_since"]
                last_wid = last_loc.split(":")[0] if last_loc and last_loc not in SPECIAL_LOCATION else None
                last_world = client.get_world_name(last_wid, db, cache_only=True) if last_wid else None
                last_label = parse_location(last_loc)[2] if last_wid else ""
                body = f"在线 {fmt_duration(dur)}（{fmt_ts(info['online_since'])} ~ {fmt_ts(now)}）"
                if last_world:
                    body += f" · 最后位置: {last_world}（{last_label}）"
                if watched(info["name"], fid):
                    if was_active:
                        if cfg.get("notify_active_offline", True):
                            push(cfg, f"🟠 {info['name']} 网页下线了", body)
                    elif cfg.get("notify_offline", True):
                        push(cfg, f"🔴 {info['name']} 下线了", body)
                db.execute("INSERT INTO events (friend_id,display_name,event,ts,duration,"
                           "world_name,location,prev_state) VALUES (?,?,?,?,?,?,?,?)",
                           (fid, info["name"], "offline", now, dur, last_world, last_loc,
                            "active" if was_active else "online"))
                log(f"🟠网页 {info['name']} 下线 | {body}" if was_active
                    else f"🔴 {info['name']} 下线 | {body}")
        # 定期同步完整好友列表（含离线），供网页"好友"页使用
        if now >= next_offline_sync:
            next_offline_sync = now + 300
            try:
                offline_friends = client.get_friends(offline=True)
                rows = {}
                for f in list(friends) + offline_friends:
                    fid2 = f.get("id")
                    if not fid2 or fid2 in rows:
                        continue
                    ftags = f.get("tags")
                    rows[fid2] = (fid2, f.get("displayName") or f.get("username") or "?",
                                  f.get("username"),
                                  json.dumps(ftags, ensure_ascii=False) if ftags else None,
                                  f.get("last_platform"),
                                  str(f.get("last_login")) if f.get("last_login") else None,
                                  now,
                                  f.get("currentAvatarImageUrl") or "",
                                  f.get("last_activity") or "")
                
                # 历史人物详情仍可秒出（web 详情查询不含 in_roster 过滤）
                if rows:
                    ph = ",".join("?" * len(rows))
                    db.execute(f"UPDATE friends_all SET in_roster=0 "
                               f"WHERE friend_id NOT IN ({ph})", list(rows.keys()))
                else:
                    db.execute("UPDATE friends_all SET in_roster=0 WHERE in_roster=1")
                db.executemany("INSERT OR REPLACE INTO friends_all "
                               "(friend_id,display_name,username,tags,last_platform,"
                               "last_login,updated_at,thumb,last_activity,in_roster) "
                               "VALUES (?,?,?,?,?,?,?,?,?,1)",
                               list(rows.values()))
                log(f"好友列表已同步: {len(rows)} 人（其中离线 {len(offline_friends)} 人）")
            except (requests.RequestException, AuthExpired) as e:
                log(f"离线好友同步失败，下一轮重试: {e}")
                next_offline_sync = now + 60
        db.commit()
        # 正常节奏: 每 poll 秒一轮；WebSocket 事件 / 网页手动刷新都会立刻唤醒
        last_refresh_seen[0] = _wait_wake_or_refresh(wake, _poll_delay(poll), last_refresh_seen[0])
        if last_refresh_seen[0] < 0:
            last_refresh_seen[0] = 0
            time.sleep(2)  # 事件突发去抖 / 手动刷新去抖


# ---------- 一次性命令 ----------
def once(cfg, db):
    client = VRChatClient(cfg)
    if not os.path.exists(AUTH_PATH) or not client.is_logged_in():
        print("尚未登录 VRChat。请先运行: ./venv/bin/python3 vrc_watch.py auth")
        sys.exit(1)
    friends = client.get_friends()
    watch_ids = set()
    if cfg.get("watch_favorites", True):
        try:
            watch_ids.update(client.get_favorite_friend_ids())
        except (AuthExpired, requests.RequestException) as e:
            print(f"收藏夹获取失败: {e}")
    watch_names = {w.lower() for w in cfg.get("watch_list") or []}
    rows = []
    for f in friends:
        name = f.get("displayName") or ""
        if (watch_ids or watch_names) and f.get("id") not in watch_ids \
                and name.lower() not in watch_names:
            continue
        loc = f.get("location") or ""
        if loc in SPECIAL_LOCATION:
            world = SPECIAL_LOCATION[loc]
        else:
            world = client.get_world_name(loc.split(":")[0], db) or loc
        status = STATUS_MAP.get(f.get("status", ""), f.get("status", "")) or "在线"
        plat = PLATFORM_MAP.get((f.get("last_platform") or "").lower(), f.get("last_platform") or "?")
        desc = f.get("statusDescription") or ""
        rows.append((name, world, status, plat, desc))
    rows.sort()
    print(f"当前在线关注好友 {len(rows)} 人（好友总在线 {len(friends)}）:")
    for name, world, status, plat, desc in rows:
        extra = f" · {desc}" if desc else ""
        print(f"  {name}  | {world} | {status} | {plat}{extra}")
    if not rows:
        print("  （没有符合条件的好友在线）")


def show_history(db, name=None, days=3):
    since = now_ts() - days * 86400
    if name:
        rows = db.execute(
            "SELECT display_name, event, ts, duration, world_name FROM events "
            "WHERE display_name LIKE ? AND ts >= ? ORDER BY ts DESC LIMIT 200",
            (f"%{name}%", since)).fetchall()
    else:
        rows = db.execute(
            "SELECT display_name, event, ts, duration, world_name FROM events "
            "WHERE ts >= ? ORDER BY ts DESC LIMIT 200", (since,)).fetchall()
    if not rows:
        print("（暂无记录）")
        return
    for dname, event, ts, dur, world in rows:
        if event == "online":
            extra = f"世界: {world}" if world else ""
            print(f"{fmt_ts(ts)}  🟢 {dname} 上线  {extra}")
        else:
            print(f"{fmt_ts(ts)}  🔴 {dname} 下线  在线 {fmt_duration(dur) if dur else '时长未知'}")


def auth_flow(cfg):
    client = VRChatClient(cfg)
    print("== VRChat 登录（输入的密码不会回显，也不会明文出现在日志里）==")
    username = ask("用户名/邮箱: ")
    password = getpass.getpass("密码: ").strip()
    store = (ask("保存账号密码用于 cookie 过期后自动重登? (y/N): ").lower() == "y")
    totp_secret = (cfg.get("totp_secret") or "").strip() or None
    if store and not totp_secret:
        print("提示: 若开了2FA，全自动重登还需 TOTP 密钥(base32)；没有就回车跳过，"
              "过期时脚本会推送提醒你手动登录。")
        totp_secret = ask("TOTP 密钥(回车跳过): ") or None
    code = None
    while True:
        try:
            client.login(username, password, totp_code=code,
                         totp_secret=totp_secret, store_creds=store)
            break
        except TwoFactorRequired as e:
            if "totp" in e.kinds:
                code = ask("请输入验证器 App 的 2FA 验证码(6位): ")
            elif "emailOtp" in e.kinds:
                code = ask("请输入邮箱收到的验证码: ")
            else:
                code = ask("请输入恢复代码(recovery code): ")
    print("登录完成。监控服务会在下一个轮询周期自动开始工作，无需重启。")


def _await_monitor_enable():
    path = os.environ.get('VRCX_PI_MONITOR_PAUSE_FILE')
    if path and os.path.exists(path):
        log('监控暂停，等待服务器迁移完成')
        while os.path.exists(path):
            time.sleep(0.5)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd in ("help", "-h", "--help"):
        print(__doc__)
        return
    cfg = load_config()
    global PROXIES
    proxy = (cfg.get("proxy") or "").strip()
    PROXIES = {"http": proxy, "https": proxy} if proxy else None
    db = init_db()
    if cmd == "auth":
        auth_flow(cfg)
    elif cmd == "run":
        _await_monitor_enable()
        watch(cfg, db)
    elif cmd == "once":
        once(cfg, db)
    elif cmd == "push":
        title = sys.argv[2] if len(sys.argv) > 2 else "🔔 vrc-watch 测试"
        body = sys.argv[3] if len(sys.argv) > 3 else "能在手表上看到这条，说明推送链路已打通"
        sys.exit(0 if push(cfg, title, body) else 1)
    elif cmd == "history":
        name = sys.argv[2] if len(sys.argv) > 2 else None
        days = int(sys.argv[3]) if len(sys.argv) > 3 else 3
        show_history(db, name, days)
    else:
        print(__doc__)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
