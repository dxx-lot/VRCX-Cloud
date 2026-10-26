"""F-14 群组成员（上游 group.js: GET groups/{groupId}/members）"""
def get_members(transport, group_id, n=50, offset=0):
    import requests
    try:
        r = transport.get(
            f"https://api.vrchat.cloud/api/1/groups/{group_id}/members",
            params={"n": n, "offset": offset}, timeout=25)
    except Exception as e:
        return {"error": f"网络错误: {e}"}
    if r.status_code != 200:
        return {"error": f"HTTP {r.status_code}（可能非成员不可见）"}
    try:
        members = r.json()
    except ValueError:
        return {"error": "响应解析失败"}
    out = []
    for m in members:
        u = m.get("user") or {}
        out.append({"id": m.get("userId") or u.get("id"),
                    "name": u.get("displayName") or u.get("displayName") or m.get("userId")})
    return out
