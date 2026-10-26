"""Production services: session changes, logout locking, data projection and relay bounds."""
import json
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "webui"))
import web
from services.assets import Assets
from services.session import SessionScope, SingleFlight
from services.feed import FeedRepository
from services.peer import relay_url
from services.routes import ApiRouter


def response(payload, status=200):
    r = requests.Response()
    r.status_code = status
    r._content = json.dumps(payload).encode()
    return r


@pytest.fixture
def scope(monkeypatch, tmp_path):
    auth = tmp_path / "auth-ui.json"
    auth.write_text("{}")
    monkeypatch.setattr(web, "AUTH_PATH", str(auth))
    monkeypatch.setattr(web, "UI_AUTH_PATH", str(auth))
    monkeypatch.setattr(web, "DB_PATH", str(tmp_path / "db.sqlite"))
    web._invalidate_session()
    return auth


def client(name):
    session = requests.Session()
    session.get = lambda url, **kw: response({"id": "usr_" + name, "displayName": name, "username": name})
    return type("Client", (), {"s": session})()


def test_replaced_auth_file_cannot_reuse_previous_account_cache(scope):
    assert web.get_self(client("A"))["name"] == "A"
    new = scope.with_suffix(".new")
    new.write_text('{"revision": 2}')
    new.replace(scope)
    assert web.get_self(client("B"))["name"] == "B"


def test_account_details_are_keyed_by_user(scope):
    assert web._acct_details(client("A"), "usr_A")["username"] == "A"
    assert web._acct_details(client("B"), "usr_B")["username"] == "B"


def test_network_reply_from_logged_out_session_cannot_repopulate_cache(scope):
    started, release = threading.Event(), threading.Event()
    c = client("A")
    original = c.s.get
    def delayed(*args, **kwargs):
        started.set()
        assert release.wait(3)
        return original(*args, **kwargs)
    c.s.get = delayed
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(web.get_self, c, True)
        assert started.wait(3)
        scope.write_text('{"revision": 3}')
        web._invalidate_session()
        release.set()
        assert pending.result(3) is None
    assert web._self_cache["data"] is None


def test_returned_self_payload_cannot_mutate_cached_identity(scope):
    s = web.get_self(client("A"))
    s["name"] = "bad"
    assert web.get_self(client("A"))["name"] == "A"


def test_logout_and_cookie_clear_do_not_reenter_a_nonreentrant_lock(monkeypatch, scope):
    monkeypatch.setattr(web, "load_config", lambda: {})
    class Dummy:
        def __init__(self, cfg):
            self.s = requests.Session()
            self.creds = None
        def _save_cookies(self, path):
            Path(path).write_text("{}")
    monkeypatch.setattr(web, "VRChatClient", Dummy)
    result = []
    thread = threading.Thread(target=lambda: result.append(web.api_logout()), daemon=True)
    thread.start(); thread.join(2)
    assert not thread.is_alive(), "logout deadlocked"
    assert result[0]["ok"]
    thread = threading.Thread(target=web.adapter_cookies_clear, daemon=True)
    thread.start(); thread.join(2)
    assert not thread.is_alive(), "cookie clearing deadlocked"


def test_simultaneous_self_loads_issue_only_one_pair_of_production_requests(scope):
    started, release = threading.Event(), threading.Event()
    session = requests.Session()
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        if url.endswith("/auth/user"):
            started.set(); assert release.wait(3)
        return response({"id": "usr_A", "displayName": "A"})
    session.get = get
    c = type("Client", (), {"s": session})()
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(web.get_self, c, True) for _ in range(4)]
        assert started.wait(3)
        deadline=time.monotonic()+3
        key=(web._ensure_scope(),"self")
        while web._FLIGHTS._jobs.get(key,{}).get("waiters",0)<3 and time.monotonic()<deadline:
            time.sleep(0.001)
        assert web._FLIGHTS._jobs[key]["waiters"] == 3
        release.set()
        assert all(f.result(3)["name"] == "A" for f in futures)
    assert len(calls) == 2


@pytest.fixture
def events(tmp_path):
    path = tmp_path / "events.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE events(id INTEGER PRIMARY KEY,friend_id TEXT,display_name TEXT,event TEXT,ts INTEGER,status TEXT,prev_state TEXT)")
        conn.executemany("INSERT INTO events VALUES(?,?,?,?,?,?,?)", [
            (1,"usr_A","Same","offline",100,"busy","online"),
            (2,"usr_B","Same","offline",100,"active","active"),
            (3,"usr_A","Same","status",102,"busy","online")])
    return FeedRepository(str(path), lambda _: (None,None,None))


def test_feed_projects_status_and_ids_and_stably_orders_equal_timestamps(events):
    rows = events.read()["events"]
    assert [r["id"] for r in rows] == [3,2,1]
    assert rows[0]["status"] == "busy"


def test_history_filters_all_event_types_and_separates_web_offline(events):
    assert [r["id"] for r in events.read(event_type="offline")["events"]] == [1]
    assert [r["id"] for r in events.read(event_type="web_offline")["events"]] == [2]
    assert [r["id"] for r in events.read(event_type="status")["events"]] == [3]
    assert [r["id"] for r in events.read(friend_id="usr_B")["events"]] == [2]


@pytest.mark.parametrize("path", ["/api/peer-relay?path=/api/self", "/api/events/stream", "https://other/api/self", "//other/api/self", "/api/../self", "/api/%73elf", "/api/self?path=/api/peer-self", "/api/unknown"])
def test_peer_relay_never_recurses_or_escapes_registered_endpoints(path):
    assert isinstance(relay_url("http://127.0.0.1:8001",path,"GET",ApiRouter({}).allowed("GET")),dict)


def test_group_leave_is_post_only_and_receives_a_body():
    seen=[]
    router=ApiRouter({"api_group_leave":lambda body:seen.append(body) or {"ok":True}})
    assert router.dispatch("GET","/api/group-leave")[0] == 404
    assert router.dispatch("POST","/api/group-leave",body={"id":"grp_test"})[1]["ok"]
    assert seen == [{"id":"grp_test"}]


def test_asset_version_changes_for_js_and_paths_cannot_escape(tmp_path):
    (tmp_path/"static").mkdir();(tmp_path/"templates").mkdir();(tmp_path/"services").mkdir()
    (tmp_path/"web.py").write_text("")
    (tmp_path/"templates"/"index.html").write_text("__UI_VER__")
    js=tmp_path/"static"/"app.js";js.write_text("one")
    assets=Assets(tmp_path);old=assets.version();js.write_text("two-longer")
    assert assets.version()!=old
    assert assets.resolve("../web.py") is None
    assert assets.resolve("app.js")[0]==js


def test_session_fingerprint_does_not_read_auth_contents(tmp_path):
    scope=SessionScope();path=tmp_path/"opaque"
    path.write_bytes(b"not JSON")
    assert scope.current(path,tmp_path/"db") == scope.current(path,tmp_path/"db")


def test_response_cache_returns_copies_and_refreshes_without_blocking():
    from services.cache import ResponseCache
    jobs, calls, clock = [], [], [0]
    refresher = type('Controlled', (), {'submit': lambda self, key, work: jobs.append(work)})()
    cache = ResponseCache(refresher, limit=2, clock=lambda: clock[0])
    def work():
        calls.append(1)
        return {'items': [len(calls)]}
    first = cache.read('items', 5, work)
    first['items'].clear()
    assert cache.read('items', 5, work)['items'] == [1]
    clock[0] = 6
    assert cache.read('items', 5, work) == {'items': [1], '_stale': True}
    assert len(calls) == 1
    jobs.pop()()
    assert cache.read('items', 5, work)['items'] == [2]


def test_response_cache_supports_group_member_arrays_and_fences_clear():
    from services.cache import ResponseCache
    refresher = type('Controlled', (), {'submit': lambda self, key, work: False})()
    cache = ResponseCache(refresher)
    calls = []
    assert cache.read('members', 30, lambda: calls.append(1) or [{'id': 'usr_1'}]) == [{'id': 'usr_1'}]
    assert cache.read('members', 30, lambda: pytest.fail('cache miss')) == [{'id': 'usr_1'}]
    cache.clear()
    def old():
        cache.clear()
        return {'name': 'old'}
    assert 'error' in cache.read('profile', 30, old)
    assert not cache.entries


def test_background_refresher_deduplicates_and_has_no_unbounded_queue():
    from services.session import Refresher
    refresher = Refresher(workers=1)
    started, release = threading.Event(), threading.Event()
    def work():
        started.set()
        assert release.wait(3)
    try:
        assert refresher.submit('same', work)
        assert started.wait(3)
        assert not refresher.submit('same', work)
        assert not refresher.submit('other', work)
    finally:
        release.set()
        refresher._pool.shutdown(wait=True)
    assert not refresher._active
    assert not refresher.submit('after-shutdown', work)


def test_http_adapter_gzips_assets_and_keeps_private_versioned_cache():
    import gzip
    import io
    h = object.__new__(web.Handler)
    h.headers = {'Accept-Encoding': 'gzip'}
    h.wfile = io.BytesIO()
    headers = {}
    h.send_response = lambda status: headers.update(status=status)
    h.send_header = lambda key, value: headers.update({key: value})
    h.end_headers = lambda: None
    payload = b'var example = 1;\n' * 100
    h._send(200, payload, 'text/javascript', static=True)
    assert gzip.decompress(h.wfile.getvalue()) == payload
    assert len(h.wfile.getvalue()) < len(payload)
    assert headers['Content-Length'] == str(len(h.wfile.getvalue()))
    assert headers['Cache-Control'].startswith('private,')
    assert headers['Content-Encoding'] == 'gzip'


def test_backup_route_uses_runtime_data_directory_and_real_sqlite(monkeypatch, tmp_path):
    db = tmp_path / 'runtime.sqlite'
    with sqlite3.connect(db) as c:
        c.execute('CREATE TABLE example (id INTEGER)')
        c.execute('INSERT INTO example VALUES (7)')
    monkeypatch.setattr(web, 'DB_PATH', str(db))
    monkeypatch.setattr(web, 'DIR', str(tmp_path))
    result = web.api_backup_op({'op': 'create'})
    assert result['ok']
    listing = web.api_backup({})
    assert result['file'] in listing['backups']
    with sqlite3.connect(tmp_path / 'backups' / result['file']) as c:
        assert c.execute('SELECT id FROM example').fetchone() == (7,)


def test_atomic_cookie_persistence_keeps_old_file_when_replace_fails(monkeypatch, tmp_path):
    import os
    monkeypatch.setattr(web.vrc_watch, 'AUTH_PATH', str(tmp_path / 'missing-auth.json'))
    c = web.vrc_watch.VRChatClient({'user_agent': 'test'})
    path = tmp_path / 'auth-ui.json'
    path.write_text('{"revision": 1}')
    original = os.replace
    def fail(source, target):
        if str(target) == str(path):
            raise OSError('test replace failure')
        return original(source, target)
    monkeypatch.setattr(os, 'replace', fail)
    with pytest.raises(OSError):
        c._save_cookies(str(path))
    assert json.loads(path.read_text()) == {'revision': 1}
    assert not list(tmp_path.glob('.auth-*'))


def test_late_world_reply_cannot_repopulate_a_replaced_session_cache(scope):
    c=client('A')
    def get(url, **kw):
        scope.write_text('{"revision": 20}')
        web._invalidate_session()
        return response({'name':'old-world'})
    c.s.get=get
    assert web.fetch_world(c,'wrld_test') is None
    assert not web._world_cache


def test_export_is_routable_through_peer_and_returns_a_json_envelope(monkeypatch,tmp_path):
    from export_import import export_friends_csv
    monkeypatch.setattr(web,'DB_PATH',str(tmp_path/'export.db'))
    monkeypatch.setattr(sys.modules['export_import'],'export_friends_csv',lambda path:'id,name\nusr_A,A\n')
    status,value=ApiRouter(vars(web)).dispatch('GET','/api/export',{'kind':['friends.csv'],'format':['json']})
    assert status==200 and value['content_type']=='text/csv'
    assert value['content'].startswith('id,name\n')
    assert '/api/export' in ApiRouter({}).allowed('GET')
    assert relay_url('http://localhost:8001','/api/export?format=json&kind=friends.csv','GET',ApiRouter({}).allowed('GET')).endswith('kind=friends.csv')


def test_route_registry_has_no_missing_handlers():
    from services.routes import ENDPOINTS
    assert len({(r.method,r.path) for r in ENDPOINTS})==len(ENDPOINTS)
    for route in ENDPOINTS:
        assert callable(vars(web).get(route.handler)), route


def test_login_and_logout_may_change_session_generation_without_losing_success():
    generation=[1]
    def mutate():
        generation[0]+=1
        return {'ok':True}
    router=ApiRouter({'api_logout':mutate},scope=lambda:generation[0])
    assert router.dispatch('POST','/api/logout')==(200,{'ok':True})
    def read():
        generation[0]+=1
        return {'name':'old'}
    router=ApiRouter({'api_self':read},scope=lambda:generation[0])
    assert 'error' in router.dispatch('GET','/api/self')[1]


def test_old_web_client_cannot_be_reused_under_a_new_account(scope,monkeypatch):
    monkeypatch.setattr(web,'_VRChatClient',lambda cfg:client('A'))
    old=web.VRChatClient({})
    assert web.get_self(old)['name']=='A'
    scope.write_text('{"revision": 30}')
    web._invalidate_session()
    assert web.get_self(old) is None
    assert web.fetch_world(old,'wrld_test') is None
    assert web._acct_details(old,'usr_A')=={}
    assert web._self_cache['data'] is None


def test_static_script_tags_work_without_a_data_api_token(monkeypatch):
    h=object.__new__(web.Handler)
    h.path='/static/core/runtime.js?v='+web._ASSETS.version()
    h.headers={}
    seen=[]
    h._send=lambda *args,**kwargs:seen.append((args,kwargs))
    monkeypatch.setattr(web,'load_config',lambda:pytest.fail('static code must not read account config'))
    h.do_GET()
    assert seen[0][0][0]==200 and b'Context' in seen[0][0][1]
    assert seen[0][1]['static']
    h.path='/api/self'
    monkeypatch.setattr(web,'load_config',lambda:{'web_password':'synthetic-access-password'})
    h.do_GET()
    assert seen[-1][0][0]==401
