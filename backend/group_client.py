"""F-14 群组管理（上游 group.js 端点等价）"""
import requests

BASE = "https://api.vrchat.cloud/api/1/"


def leave_group(transport, group_id, my_id):
    from errors import AuthCode, AuthResult
    try:
        r = transport.delete(f"{BASE}groups/{group_id}/members/{my_id}", timeout=20)
    except Exception as e:
        return AuthResult(AuthCode.NETWORK_ERROR, raw=str(e))
    if r.status_code in (200, 204):
        return AuthResult(AuthCode.OK)
    return AuthResult(AuthCode.SERVER_ERROR, raw=f"HTTP {r.status_code}")


def get_group_posts(transport, group_id):
    try:
        r = transport.get(f"{BASE}groups/{group_id}/posts", timeout=20)
    except requests.RequestException as e:
        return {"ok_count": 0, "posts": [], "error": f"网络错误: {e}"}
    if r.status_code != 200:
        return {"ok_count": 0, "posts": [], "error": f"HTTP {r.status_code}"}
    posts = r.json()
    return {"ok_count": len(posts), "posts": posts}


def get_group(transport, group_id):
    """上游 group.js getGroup：GET groups/{groupId}?includeRoles=false"""
    try:
        r = transport.get(
            f"https://api.vrchat.cloud/api/1/groups/{group_id}",
            params={"includeRoles": "false"}, timeout=20)
    except Exception as e:
        from errors import AuthResult, AuthCode
        return AuthResult(AuthCode.NETWORK_ERROR, raw=str(e))
    if r.status_code != 200:
        return None
    g = r.json()
    return {"id": g.get("id"), "name": g.get("name"),
            "description": g.get("description") or "",
            "memberCount": g.get("memberCount"),
            "icon": g.get("iconUrl") or "", "banner": g.get("bannerUrl") or "",
            "visibility": g.get("visibility") or "",
            "joining": g.get("joining"), "createdAt": g.get("createdAt") or ""}
