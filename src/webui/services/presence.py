"""Presence confirmation, independent of polling, transport and storage.

VRCX friendPresenceCoordinator defers game -> web/offline transitions and cancels
them on recovery. Pi confirms two observations over 30s; upstream uses 170s.
"""
from copy import deepcopy


def state_of(user):
    state = user.get('state')
    if state in ('online', 'active', 'offline'):
        return state
    loc = user.get('location') or ''
    return 'online' if loc and loc != 'offline' else 'active'


def confirmed_session_start(db, uid, state, stored, now):
    """Correct inherited game/web starts only from the latest explicit transition.
    Historical events remain immutable; a monitor restart is not a new session.
    """
    row = db.execute("SELECT event,ts FROM events WHERE friend_id=? AND ts<=? "
                     "AND event IN ('online','active','offline') ORDER BY ts DESC,id DESC LIMIT 1", (uid, now)).fetchone()
    expected = 'online' if state == 'online' else 'active'
    if row and row[0] == expected and stored is not None and stored < row[1] <= now:
        return row[1]
    return stored


class PresenceGate:
    def __init__(self, delay=30):
        self.delay = delay
        self.previous = {}
        self.pending = {}

    def forget(self, uid):
        self.previous.pop(uid, None)
        self.pending.pop(uid, None)

    def apply(self, snapshot, now):
        out = deepcopy(snapshot)
        for uid, old in self.previous.items():
            new = snapshot.get(uid)
            state = new.get('state') if new else 'offline'
            # API gaps and short game disconnects cannot create false sessions.
            leaving = new is None or (old.get('state') == 'online' and state == 'active')
            if leaving:
                pending = self.pending.get(uid)
                if not pending or pending[0] != state:
                    self.pending[uid] = (state, now)
                    pending = self.pending[uid]
                if now - pending[1] < self.delay:
                    held = dict(old, **(new or {}))
                    held['state'] = old['state']
                    if 'location' in old or 'location' in held:
                        held['location'] = old.get('location', '')
                    out[uid] = deepcopy(held)
                    continue
            self.pending.pop(uid, None)
        for uid in snapshot:
            if snapshot[uid].get('state') == self.previous.get(uid, {}).get('state'):
                self.pending.pop(uid, None)
        self.previous = deepcopy(out)
        return out
