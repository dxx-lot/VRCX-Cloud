/* Shared feed semantics: HTTP snapshots, SSE and merged views use one model. */
(function (root, factory) {
  const model = factory();
  if (typeof module === 'object' && module.exports) module.exports = model;
  else root.VRCXFeed = model;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const fields = ['friend_id', 'event', 'location', 'status', 'status_description',
    'previous', 'previous_location', 'previous_desc', 'prev_state', 'avatar', 'world_name'];
  const signature = e => JSON.stringify(fields.map(k => e[k] ?? ''));
  const identity = e => `${e._src || 'a'}:${e.id != null ? e.id : JSON.stringify([e.ts, signature(e)])}`;
  const eventType = e => e.event === 'offline' && e.prev_state === 'active' ? 'web_offline' : e.event;

  function normalize(events, source) {
    const unique = new Map();
    for (const raw of events || []) {
      if (!raw || !raw.friend_id || !raw.event || !Number.isFinite(Number(raw.ts))) continue;
      const e = {...raw, _src: source || raw._src || 'a'};
      unique.set(identity(e), e);
    }
    return [...unique.values()].sort((a, b) => Number(b.ts) - Number(a.ts) || Number(b.id || 0) - Number(a.id || 0));
  }

  function mergeEvents(a, b, tolerance = 3) {
    const events = [...normalize(a, 'a'), ...normalize(b, 'b')].sort((x, y) => Number(y.ts) - Number(x.ts));
    const buckets = new Map(), merged = [];
    for (const e of events) {
      const key = signature(e), bucket = buckets.get(key) || [];
      // Only equal payloads observed by different accounts can be twins. Same-account
      // transitions (and different rooms/statuses) remain independent events.
      const twin = bucket.find(x => x._src !== e._src && x._src !== 'ab' && Math.abs(x.ts - e.ts) <= tolerance);
      if (twin) {
        twin._sources[e._src] = e.id;
        twin._src = 'ab';
      } else {
        const row = {...e, _sources: {[e._src]: e.id}};
        bucket.push(row); merged.push(row);
      }
      buckets.set(key, bucket);
    }
    return merged;
  }

  function mergeFriends(a, b) {
    const rows = new Map();
    const rank = f => f.state === 'online' || (f.online && !f.web_online) ? 2 : f.web_online || f.state === 'active' ? 1 : 0;
    for (const [source, friends] of [['a', a], ['b', b]]) {
      for (const f of friends || []) {
        if (!f || !f.id) continue;
        const prev = rows.get(f.id);
        const accounts = {...(prev?._accounts || {}), [source]: {...f}};
        const winner = !prev || rank(f) > rank(prev) ? {...f, _detailSource: source} : prev;
        rows.set(f.id, {...winner, _accounts: accounts, _src: Object.keys(accounts).sort().join('')});
      }
    }
    return [...rows.values()].sort((a, b) => (a.name || '').localeCompare(b.name || ''));
  }

  function mergePayload(a, b) {
    const valid = v => v && !v.error && !v.peer_error && v.peer_configured !== false;
    const va = valid(a) ? a : null, vb = valid(b) ? b : null;
    if (!va && !vb) throw new Error(a?.error || b?.error || '两个账号的数据均不可用');
    const out = {...(va || vb), _accounts: {a: va, b: vb}, _errors: {a: va ? null : a?.error || '不可达', b: vb ? null : b?.error || '不可达'}};
    if (Array.isArray(va?.events) || Array.isArray(vb?.events)) out.events = mergeEvents(va?.events, vb?.events);
    if (Array.isArray(va?.friends) || Array.isArray(vb?.friends)) out.friends = mergeFriends(va?.friends, vb?.friends);
    return out;
  }

  function locationText(e) {
    const loc = e.location || '';
    if (loc === 'private') return '位于私人房间';
    if (loc === 'traveling') return '正在传送';
    if (loc.startsWith('wrld_')) return e.world_name || '世界信息未缓存';
    return loc === 'offline' ? '网页在线' : '位置未知';
  }
  return {locationText, identity, signature, eventType, normalize, mergeEvents, mergeFriends, mergePayload};
});
