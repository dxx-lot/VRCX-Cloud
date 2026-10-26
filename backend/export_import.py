"""F-21 导出（好友列表 CSV / 活动 JSON，不含任何凭据）"""
import csv
import io
import sqlite3


def export_friends_csv(db_path):
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT friend_id, display_name, username, last_platform, last_login "
            "FROM friends_all ORDER BY display_name")]
    finally:
        conn.close()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["id", "displayName", "username", "platform", "last_login"])
    for r in rows:
        w.writerow([r["friend_id"], r["display_name"], r["username"] or "",
                    r["last_platform"] or "", r["last_login"] or ""])
    return out.getvalue()


def export_events_json(db_path, days=30):
    import time
    since = int(time.time()) - days * 86400
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT display_name, event, ts, duration, world_name, location, "
            "status_description FROM events WHERE ts >= ? ORDER BY ts DESC", (since,))]
    finally:
        conn.close()
    return {"events": rows}
