"""Validate peer paths against the real route registry; never relay recursively."""
from urllib.parse import urlsplit, parse_qs, unquote


def relay_url(peer, path, method, allowed):
    parts = urlsplit(path)
    decoded = unquote(parts.path)
    if (parts.scheme or parts.netloc or parts.fragment or decoded != parts.path
            or ".." in decoded or "\\" in decoded or parts.path not in allowed
            or parts.path.startswith("/api/peer-") or parts.path == "/api/events/stream"):
        return {"error": "非法转发路径"}
    if not peer:
        return {"error": "未配置对端实例（peer_url）"}
    query = parse_qs(parts.query)
    if "path" in query:
        return {"error": "非法转发路径"}
    return peer.rstrip("/") + path
