"""F-21 收藏分组导入（上游 Favorites/dialogs/*ImportDialog 流程端点等价）：
逐组 POST auth/user/favgroups 建夹——组已存在(400)时忽略错误继续加成员；
逐条 POST favorites 加入。单条失败不中断整批；返回成功/失败计数。"""
def import_favorite_groups(transport, payload, my_id):
    ftype = payload.get("type") or "friend"
    ok_count = fail_count = 0
    for g in payload.get("groups") or []:
        gname = (g.get("name") or "").strip()
        items = g.get("items") or []
        if not gname:
            fail_count += len(items)
            continue
        # 建夹：已存在(400)不算失败——VRCX ImportDialog 同款语义
        try:
            transport.post("auth/user/favgroups",
                           {"type": ftype, "name": gname, "displayName": gname})
        except Exception:
            pass
        for uid in items:
            try:
                r2 = transport.post("favorites",
                                    {"type": ftype, "favoriteId": uid, "tags": [gname]})
                if r2[0] in (200, 201):
                    ok_count += 1
                else:
                    fail_count += 1
            except Exception:
                fail_count += 1
    return {"ok_count": ok_count, "fail_count": fail_count}
