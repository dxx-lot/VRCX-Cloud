"""F-19 VRChat 服务状态（上游 vrcStatus.js）+ F-14 群组详情（上游 group.js getGroup）"""
import requests

VRC_STATUS_URL = "https://status.vrchat.com/api/v2/status.json"
VRC_STATUS_REFERER = "https://vrcx.app"


def _fetch_raw(timeout):
    r = requests.get(VRC_STATUS_URL, timeout=timeout,
                     headers={"Referer": VRC_STATUS_REFERER})
    r.raise_for_status()
    return parse_status_json(r.json(), fetched=True)


def fetch_vrc_status(timeout=8):
    """硬超时 12s（DNS 挂起不受 requests timeout 保护，用线程兜底）。
    超时/失败 → issue=True + fetch_error，调用方有 120s 缓存。"""
    import threading
    out = {}
    def run():
        try:
            out["data"] = _fetch_raw(timeout)
        except Exception as e:
            out["err"] = e
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(12)
    if "data" in out:
        return out["data"]
    return {"issue": True, "summary": "无法获取服务状态（网络/超时）",
            "indicator": "unknown", "updated": None,
            "fetch_error": str(out.get("err", "timeout"))}


def parse_status_json(data, fetched=False):
    st = (data.get("status") or {})
    desc = st.get("description") or ""
    out = {"issue": desc != "All Systems Operational",
           "summary": "" if desc == "All Systems Operational" else desc,
           "indicator": st.get("indicator") or "none",
           "updated": (data.get("page") or {}).get("updated_at") or ""}
    if fetched:
        out["updated"] = out["updated"] or ""
    return out


def get_group(session, group_id):
    """上游 group.js getGroup：GET groups/{groupId}?includeRoles=false"""
    r = session.get(f"https://api.vrchat.cloud/api/1/groups/{group_id}",
                    params={"includeRoles": "false"}, timeout=20)
    if r.status_code != 200:
        return None
    g = r.json()
    return {"id": g.get("id"), "name": g.get("name"),
            "description": g.get("description") or "",
            "memberCount": g.get("memberCount"),
            "icon": g.get("iconUrl") or "", "banner": g.get("bannerUrl") or "",
            "visibility": g.get("visibility") or "",
            "joining": g.get("joining"), "createdAt": g.get("createdAt") or ""}
