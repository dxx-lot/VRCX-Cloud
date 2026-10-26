"""One route catalogue shared by the HTTP adapter and peer allowlist."""

from dataclasses import dataclass
import json

# Local SQLite snapshots stay live. Network-heavy views share cached work and
# return their last successful result while a bounded worker refreshes it.
LIVE_TTLS = {"/api/favgroups": 30, "/api/favorites": 30, "/api/notifications": 15,
             "/api/avatars": 60, "/api/avatar": 60, "/api/moderations": 30,
             "/api/group": 30, "/api/group-members": 30,
             "/api/search": 15, "/api/world-search": 15,
             "/api/group-search": 15}

@dataclass(frozen=True)
class Endpoint:
    method: str
    path: str
    handler: str
    argument: str = "none"
    field: str = ""

ENDPOINTS = (
    Endpoint('GET', '/api/image', 'api_image', 'q', ''),
    Endpoint('GET', '/api/export', 'api_export', 'q', ''),
    Endpoint('GET', '/api/export-events', 'api_export_events', 'none', ''),
    Endpoint('GET', '/api/status', 'api_status', 'none', ''),
    Endpoint('GET', '/api/self', 'api_self', 'none', ''),
    Endpoint('GET', '/api/history', 'api_history', 'q', ''),
    Endpoint('GET', '/api/friendlog', 'api_friendlog', 'q', ''),
    Endpoint('GET', '/api/mutual-graph', 'api_mutual_graph', 'none', ''),
    Endpoint('GET', '/api/status-presets', 'api_presets_get', 'none', ''),
    Endpoint('GET', '/api/vrc-status', 'api_vrc_status', 'none', ''),
    Endpoint('GET', '/api/favgroups', 'api_favgroups', 'q', ''),
    Endpoint('GET', '/api/friends', 'api_friends', 'none', ''),
    Endpoint('GET', '/api/feed', 'api_feed', 'none', ''),
    Endpoint('GET', '/api/stats', 'api_stats', 'q', ''),
    Endpoint('GET', '/api/search', 'api_search', 'q', ''),
    Endpoint('GET', '/api/world-search', 'api_world_search', 'q', ''),
    Endpoint('GET', '/api/random-world', 'api_random_world', 'none', ''),
    Endpoint('GET', '/api/world', 'api_world', 'q', ''),
    Endpoint('GET', '/api/instance', 'api_instance', 'q', ''),
    Endpoint('GET', '/api/favorites', 'api_favorites', 'none', ''),
    Endpoint('GET', '/api/notifications', 'api_notifications', 'none', ''),
    Endpoint('GET', '/api/avatars', 'api_avatars', 'none', ''),
    Endpoint('GET', '/api/moderations', 'api_moderations', 'none', ''),
    Endpoint('GET', '/api/friend-section', 'api_friend_section', 'q', ''),
    Endpoint('GET', '/api/friend', 'api_friend', 'field', 'id'),
    Endpoint('GET', '/api/group', 'api_group', 'q', ''),
    Endpoint('GET', '/api/group-members', 'api_group_members', 'q', ''),
    Endpoint('GET', '/api/backup', 'api_backup', 'q', ''),
    Endpoint('GET', '/api/group-search', 'api_group_search', 'q', ''),
    Endpoint('GET', '/api/avatar', 'api_avatar', 'field', 'id'),
    Endpoint('GET', '/api/config', 'api_config', 'none', ''),
    Endpoint('GET', '/api/push-config', 'api_push_config', 'none', ''),
    Endpoint('GET', '/api/net-stats', 'api_net_stats', 'none', ''),
    Endpoint('GET', '/api/peer-self', 'api_peer_self', 'none', ''),
    Endpoint('GET', '/api/peer-feed', 'api_peer_get', 'constant', '/api/feed'),
    Endpoint('GET', '/api/peer-relay', 'api_peer_relay_get', 'field', 'path'),
    Endpoint('GET', '/api/peer-friends', 'api_peer_get', 'constant', '/api/friends'),
    Endpoint('GET', '/api/ui-version', 'api_ui_version', 'none', ''),
    Endpoint('POST', '/api/login', 'api_login', 'body', ''),
    Endpoint('POST', '/api/push-test', 'api_push_test', 'none', ''),
    Endpoint('POST', '/api/refresh', 'api_refresh', 'none', ''),
    Endpoint('POST', '/api/friend-note', 'api_friend_note', 'body', ''),
    Endpoint('POST', '/api/log-delete', 'api_log_delete', 'body', ''),
    Endpoint('POST', '/api/friend-delete', 'api_friend_delete', 'body', ''),
    Endpoint('POST', '/api/favgroup-create', 'api_favgroup_create', 'body', ''),
    Endpoint('POST', '/api/favgroup-import', 'import_favorite_groups_via_session', 'body', ''),
    Endpoint('POST', '/adapter/webapi/execute-json', 'adapter_webapi_endpoint', 'body', ''),
    Endpoint('POST', '/adapter/dotnet', 'adapter_dotnet', 'body', ''),
    Endpoint('POST', '/adapter/sqlite/json', 'adapter_sqlite_upstream', 'body', ''),
    Endpoint('POST', '/adapter/sqlite', '_sqlite_rows', 'body', ''),
    Endpoint('POST', '/adapter/sqlite/nonquery', 'adapter_sqlite_nonquery', 'body', ''),
    Endpoint('POST', '/adapter/cookies/set', 'adapter_cookies_set', 'body', ''),
    Endpoint('POST', '/adapter/cookies/clear', 'adapter_cookies_clear', 'none', ''),
    Endpoint('POST', '/api/world-note', 'api_world_note', 'body', ''),
    Endpoint('POST', '/api/config-set', 'api_config_set', 'body', ''),
    Endpoint('POST', '/api/avatar-select', 'api_avatar_select', 'body', ''),
    Endpoint('POST', '/api/favorite-op', 'api_favorite_op', 'body', ''),
    Endpoint('POST', '/api/preset-add', 'api_preset_add', 'body', ''),
    Endpoint('POST', '/api/preset-remove', 'api_preset_remove', 'body', ''),
    Endpoint('POST', '/api/notification-act', 'api_notification_act', 'body', ''),
    Endpoint('POST', '/api/backup-restore', 'api_backup_restore', 'body', ''),
    Endpoint('POST', '/api/backup-op', 'api_backup_op', 'body', ''),
    Endpoint('POST', '/api/moderate', 'api_moderate', 'body', ''),
    Endpoint('POST', '/api/set-status', 'api_set_status', 'body', ''),
    Endpoint('POST', '/api/push-config-set', 'api_push_config_set', 'body', ''),
    Endpoint('POST', '/api/peer-login', 'api_peer_login', 'body', ''),
    Endpoint('POST', '/api/peer-logout', 'api_peer_logout', 'none', ''),
    Endpoint('POST', '/api/peer-relay-post', 'api_peer_relay_post', 'path_body', ''),
    Endpoint('POST', '/api/logout', 'api_logout', 'none', ''),
    Endpoint('POST', '/api/group-leave', 'api_group_leave', 'body', ''),
    Endpoint('GET', '/api/invite-messages', 'api_invite_messages', 'field', 'type'),
)

class ApiRouter:
    def __init__(self, services, cache=None, scope=None):
        self.services = services
        self.cache = cache
        self.scope = scope
        self.routes = {(r.method, r.path): r for r in ENDPOINTS}

    def allowed(self, method):
        return {path for verb, path in self.routes if verb == method}

    def dispatch(self, method, path, query=None, body=None):
        endpoint = self.routes.get((method, path))
        if endpoint is None:
            return 404, {"error": "not found"}
        query, body = query or {}, body or {}
        fn = self.services[endpoint.handler]
        if endpoint.argument == "q": args = [query]
        elif endpoint.argument == "body": args = [body]
        elif endpoint.argument == "constant": args = [endpoint.field]
        elif endpoint.argument == "field": args = [(query.get(endpoint.field) or [""])[0].strip()]
        elif endpoint.argument == "path_body": args = [(query.get("path") or [""])[0], body]
        else: args = []
        epoch = self.scope() if self.scope else None
        def work():
            value = fn(*args)
            if method == "GET" and self.scope and epoch != self.scope():
                return {"error": "账号会话已变更，请刷新"}
            return value
        if method == "GET" and self.cache and path in LIVE_TTLS:
            key = (epoch, path, json.dumps(query, sort_keys=True))
            value = self.cache.read(key, LIVE_TTLS[path], work)
        else:
            value = work()
        if method == "POST" and self.cache and not (isinstance(value, dict) and (value.get("error") or value.get("ok") is False)):
            self.cache.clear()
        return 200, value
