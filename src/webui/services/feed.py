"""Feed/history share the same projection, filtering and stable ordering."""
import sqlite3
import time

EVENT_COLUMNS = ("id", "friend_id", "display_name", "event", "ts", "duration",
                 "world_name", "location", "status", "status_description",
                 "previous", "previous_location", "previous_desc", "prev_state", "platform")
EVENT_TYPES = {"online", "offline", "web_offline", "location", "active", "status", "desc", "avatar"}


def project_session_durations(conn, rows):
    """Read-only correction from explicit game/web transitions, never guessed.
    Keep duration as recorded for exports; consumers use session_duration.
    """
    for row in rows:
        if row.get('event') != 'offline': continue
        row['session_duration'] = None
        row['duration_source'] = 'unverified'
        if row.get('duration') is None: continue  # Restart/gap does not prove the departure time.
        start = conn.execute("SELECT event,ts FROM events WHERE friend_id=? "
            "AND (ts<? OR (ts=? AND id<?)) AND event IN ('online','active','offline') "
            "ORDER BY ts DESC,id DESC LIMIT 1", (row['friend_id'], row['ts'], row['ts'], row['id'])).fetchone()
        expected = 'active' if row.get('prev_state') == 'active' else 'online'
        if start and start[0] == expected:
            row['session_duration'] = max(0, row['ts'] - start[1])
            row['duration_source'] = 'transition'
    return rows


class FeedRepository:
    def __init__(self, db_path, parse_location):
        self.db_path = db_path
        self.parse_location = parse_location

    def read(self, limit=500, since=None, name="", event_type="", friend_id=""):
        limit = max(1, min(int(limit), 1000))
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            tables = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            last_sync = None
            if "meta" in tables:
                sync_row = conn.execute(
                    "SELECT value FROM meta WHERE key='last_sync'").fetchone()
                if sync_row:
                    try:
                        last_sync = int(float(sync_row[0]))
                    except (TypeError, ValueError, OverflowError):
                        pass
            available = {row[1] for row in conn.execute("PRAGMA table_info(events)")}
            projection = ", ".join(c if c in available else "NULL AS " + c for c in EVENT_COLUMNS)
            where, args = [], []
            if since is not None:
                where.append("ts >= ?"); args.append(since)
            if name:
                where.append("display_name LIKE ?"); args.append("%" + name + "%")
            if friend_id:
                where.append("friend_id = ?"); args.append(friend_id)
            if event_type == "web_offline":
                where.append("event = 'offline' AND prev_state = 'active'")
            elif event_type == "offline":
                where.append("event = 'offline' AND COALESCE(prev_state, '') != 'active'")
            elif event_type in EVENT_TYPES:
                where.append("event = ?"); args.append(event_type)
            sql = "SELECT " + projection + " FROM events"
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY ts DESC, id DESC LIMIT ?"
            rows = [dict(row) for row in conn.execute(sql, args + [limit])]
            project_session_durations(conn, rows)
        finally:
            conn.close()
        for row in rows:
            row["instance_label"] = self.parse_location(row.get("location") or "")[2]
        return {"events": rows, "last_sync": last_sync, "server_now": int(time.time())}
