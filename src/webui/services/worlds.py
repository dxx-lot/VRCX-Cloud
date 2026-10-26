"""Pure world/instance read models. Unknown occupancy is never reported as zero."""
import re
import json
import sqlite3


def cached_world(database, owner, wid):
    if not owner:
        return None
    try:
        with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as conn:
            row = conn.execute('SELECT ts,payload FROM world_details WHERE owner=? AND world_id=?', (owner,wid)).fetchone()
        return (row[0], json.loads(row[1])) if row else None
    except (sqlite3.Error, ValueError):
        return None


def save_world(database, owner, wid, timestamp, world):
    if not owner:
        return
    try:
        with sqlite3.connect(database) as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS world_details(owner TEXT,world_id TEXT,ts REAL,payload TEXT,PRIMARY KEY(owner,world_id))')
            conn.execute('INSERT OR REPLACE INTO world_details VALUES (?,?,?,?)', (owner,wid,timestamp,json.dumps(world,ensure_ascii=False)))
            conn.execute('DELETE FROM world_details WHERE rowid NOT IN (SELECT rowid FROM world_details ORDER BY ts DESC LIMIT 512)')
    except sqlite3.Error:
        pass


def rooms_for_world(world, friends, parse_location):
    wid = world['id']
    rooms = {}
    for entry in world.get('instances') or []:
        if isinstance(entry, (list, tuple)) and entry:
            iid, count = str(entry[0]), entry[1] if len(entry) > 1 else None
        elif isinstance(entry, dict):
            iid, count = entry.get('instanceId', ''), entry.get('userCount')
        else:
            continue
        if iid:
            rooms[wid + ':' + iid] = {'count': count, 'friends_in': []}
    for friend in friends:
        loc = friend.get('location') or ''
        if loc.startswith(wid + ':'):
            room = rooms.setdefault(loc, {'count': None, 'friends_in': []})
            room['friends_in'].append(friend.get('display_name') or friend.get('name') or '')
    result = []
    for loc, values in rooms.items():
        iid = loc.split(':', 1)[1]
        region = re.search(r'region\((\w+)\)', iid)
        result.append(dict(values, location=loc, num=iid.split('~')[0],
                           label=parse_location(loc)[2] or '公开',
                           region=region.group(1) if region else ''))
    return result
