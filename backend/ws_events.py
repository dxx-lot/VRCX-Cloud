'F-03 实时管线状态机——上游 websocket.js 语义的 Pi 后端模块。\n\n本模块为纯逻辑（无网络/无 sqlite），由 vrc_watch.py 的 ws 线程调用；\n网络连接与线程管理留在调用方。'





import json


class InMemoryFeed:
    """feed 写入接口的内存实现（测试用；生产用 SQLite INSERT OR IGNORE）。
    语义 = 上游 services/database/feed.js：created_at 参与唯一，重复忽略。"""

    def __init__(self):
        self.rows = []

    def add(self, row):
        key = (row.get("created_at"), row.get("user_id"), row.get("type"))
        for r in self.rows:
            if (r.get("created_at"), r.get("user_id"), r.get("type")) == key:
                return  # OR IGNORE
        self.rows.append(row)
        self.rows.sort(key=lambda r: r["created_at"], reverse=True)


class ReconnectPolicy:
    

    STEPS = (5.0, 30.0, 60.0)

    def __init__(self):
        self._fails = 0

    def next_delay(self, after_success):
        if after_success:
            self._fails = 0
            return self.STEPS[0]
        delay = self.STEPS[min(self._fails, len(self.STEPS) - 1)]
        self._fails += 1
        return delay


class WsPipeline:
    """handlePipeline 等价（websocket.js:185-546）+ 消息层去重（:127-130）。"""

    def __init__(self, feed):
        self.state = {}            # uid -> {state, location, status, desc, avatar, name}
        self.feed = feed
        self._last_raw = None      # 上游 :127 字节级去重
        self.closed_gracefully = True
        self._reconcile_cb = []

    # ---------- 连接生命周期 ----------
    def on_close(self, code):
        """上游 :97：1000/1001 = 优雅"""
        self.closed_gracefully = code in (1000, 1001)

    def on_reconnect(self, callback):
        self._reconcile_cb.append(callback)

    def on_open(self):
        """上游 :75-82：非优雅关闭后的重连成功 → 对账"""
        if not self.closed_gracefully:
            for cb in self._reconcile_cb:
                cb()
        self.closed_gracefully = True

    # ---------- 事件应用 ----------
    def apply(self, msg):
        raw = json.dumps(msg, sort_keys=True)
        if raw == self._last_raw:      # 上游 :127-130 pls no spam
            return
        self._last_raw = raw
        t = msg.get("type")
        content = msg.get("content")
        if isinstance(content, str):   # 上游 :131-137 二次解析
            try:
                content = json.loads(content)
            except ValueError:
                return                 # 解析失败静默忽略
        if not isinstance(content, dict):
            return
        ts = msg.get("_ts") or int(json.loads(raw).get("_ts", 0) or 0) or None
        handler = {
            "friend-online": self._friend_online,
            "friend-location": self._friend_location,
            "friend-active": self._friend_active,
            "friend-offline": self._friend_offline,
            "friend-update": self._friend_update,
        }.get(t)
        if handler:
            handler(content, ts)

    def _uid(self, content):
        return content.get("userId") or (content.get("user") or {}).get("id")

    def _record(self, content, etype, ts, **extra):
        self.feed.add({"created_at": ts or 0, "user_id": self._uid(content),
                       "type": etype, **extra})

    def _friend_online(self, c, ts):
        u = c.get("user") or {}
        uid = self._uid(c)
        if not uid:
            return
        self.state[uid] = {"state": "online",
                           "location": c.get("location") or u.get("location") or "",
                           "status": u.get("status"), "desc": u.get("statusDescription"),
                           "avatar": u.get("currentAvatarImageUrl"),
                           "name": u.get("displayName")}
        self._record(c, "online", ts)

    def _friend_location(self, c, ts):
        """上游 :358-389：state 强制 online（JANK 注释）"""
        u = c.get("user") or {}
        uid = self._uid(c)
        if not uid:
            return
        cur = self.state.setdefault(uid, {})
        cur.update({"state": "online",
                    "location": c.get("location") or u.get("location") or ""})
        if u.get("status") is not None: cur["status"] = u["status"]
        if u.get("statusDescription") is not None: cur["desc"] = u["statusDescription"]
        if u.get("currentAvatarImageUrl") is not None: cur["avatar"] = u["currentAvatarImageUrl"]
        if u.get("displayName"): cur["name"] = u["displayName"]
        self._record(c, "location", ts)

    def _friend_active(self, c, ts):
        u = c.get("user") or {}
        uid = self._uid(c)
        if not uid:
            return
        cur = self.state.setdefault(uid, {})
        cur.update({"state": "active", "location": "offline"})
        if u.get("status") is not None: cur["status"] = u["status"]
        if u.get("statusDescription") is not None: cur["desc"] = u["statusDescription"]
        if u.get("displayName"): cur["name"] = u["displayName"]
        self._record(c, "active", ts)

    def _friend_offline(self, c, ts):
        uid = self._uid(c)
        if not uid:
            return
        cur = self.state.setdefault(uid, {})
        cur.update({"state": "offline", "location": "offline"})
        self._record(c, "offline", ts)

    def _friend_update(self, c, ts):
        """上游 :354-356：applyUser——只覆盖字段，不动 state/location"""
        u = c.get("user") or {}
        uid = self._uid(c)
        if not uid:
            return
        cur = self.state.setdefault(uid, {})
        if u.get("status") is not None: cur["status"] = u["status"]
        if u.get("statusDescription") is not None: cur["desc"] = u["statusDescription"]
        if u.get("currentAvatarImageUrl") is not None: cur["avatar"] = u["currentAvatarImageUrl"]
        if u.get("displayName"): cur["name"] = u["displayName"]
