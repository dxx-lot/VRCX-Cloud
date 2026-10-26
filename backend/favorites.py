"""F-09 收藏与分组服务——上游 favorite.js @174551e 的端点等价适配。

行为对照（含方法与参数形状）：
- POST   favorites                       {type, favoriteId, tags:[组名]}
- DELETE favorites/{objectId}            objectId=fav_xxx（收藏记录 id，非实体 id）
- PUT    favorite/group/{type}/{group}/{myUid}   {displayName, visibility} 建/改名
- DELETE favorite/group/{type}/{group}/{myUid}                     清空/删组
- GET    auth/user/favoritelimits        容量
"""
import requests

from errors import AuthCode, AuthResult


class FavoriteService:
    def __init__(self, transport, current_user_id):
        self.t = transport
        self.me = current_user_id

    @staticmethod
    def _result(status, j):
        if status in (200, 201):
            return AuthResult(AuthCode.OK, raw=j)
        code = AuthCode.RATE_LIMITED if status == 429 else (
            AuthCode.SERVER_ERROR if status >= 500 else AuthCode.BAD_REQUEST)
        return AuthResult(code, raw=j)

    # ---------- 读 ----------
    def limits(self):
        st, j = self.t.get("auth/user/favoritelimits")
        return j if st == 200 else {"error": f"HTTP {st}"}

    def list_items(self, ftype, n=100):
        st, j = self.t.get("favorites")
        if st != 200:
            return []
        return [f for f in j if f.get("type") == ftype]

    # ---------- 写 ----------
    def add(self, ftype, favorite_id, group=None):
        tags = [group] if group else []
        try:
            st, j = self.t.post("favorites",
                                {"type": ftype, "favoriteId": favorite_id, "tags": tags})
        except requests.RequestException as e:
            return AuthResult(AuthCode.NETWORK_ERROR, raw=str(e))
        return self._result(st, j)

    def remove(self, object_id):
        try:
            st, j = self.t.delete(f"favorites/{object_id}")
        except requests.RequestException as e:
            return AuthResult(AuthCode.NETWORK_ERROR, raw=str(e))
        return self._result(st, j)

    def save_group(self, ftype, group, display_name=None, visibility=None):
        payload = {}
        if display_name is not None:
            payload["displayName"] = display_name
        if visibility is not None:
            payload["visibility"] = visibility
        try:
            st, j = self.t.put(f"favorite/group/{ftype}/{group}/{self.me}", json=payload)
        except requests.RequestException as e:
            return AuthResult(AuthCode.NETWORK_ERROR, raw=str(e))
        return self._result(st, j)

    def clear_group(self, ftype, group):
        try:
            st, j = self.t.delete(f"favorite/group/{ftype}/{group}/{self.me}")
        except requests.RequestException as e:
            return AuthResult(AuthCode.NETWORK_ERROR, raw=str(e))
        return self._result(st, j)
