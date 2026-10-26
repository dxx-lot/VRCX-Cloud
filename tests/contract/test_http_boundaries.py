"""HTTP read and static-file boundaries use real servers and synthetic SQLite."""
import base64
import gzip
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import sys
import threading

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/webui'))
sys.path.insert(0, str(ROOT))
import web
from src.application.gateway import Gateway, password_record
from src.application.launcher import bind_listener

TOKEN = 'synthetic-internal-token'
PASSWORD = 'synthetic-access-password'


@pytest.fixture
def account_http(tmp_path, monkeypatch):
    database = tmp_path / 'account.sqlite'
    with sqlite3.connect(database) as connection:
        connection.execute('CREATE TABLE example (value INTEGER)')
        connection.execute('INSERT INTO example VALUES (7)')
    monkeypatch.setattr(web, 'DIR', str(tmp_path))
    monkeypatch.setattr(web, 'DB_PATH', str(database))
    monkeypatch.setattr(web, 'load_config', lambda: {'web_password': TOKEN})
    monkeypatch.setattr(web, '_access_password', lambda config: TOKEN)
    monkeypatch.setattr(web, 'log', lambda *args: None)
    monkeypatch.setattr(web, '_GZIP_CACHE', {})
    server = ThreadingHTTPServer(('127.0.0.1', 0), web.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, tmp_path
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)


@pytest.fixture
def gateway_http(account_http):
    account, state = account_http
    gateway = Gateway(bind_listener('127.0.0.1', 0), account.server_address,
                      TOKEN, password=password_record(PASSWORD))
    thread = threading.Thread(target=gateway.serve_forever, daemon=True)
    thread.start()
    try:
        yield gateway, state
    finally:
        gateway.shutdown()
        gateway.server_close()
        thread.join(3)


def request(server, path, method='GET', headers=None, body=None):
    connection = HTTPConnection(*server.server_address, timeout=3)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def access():
    return {'Authorization': 'Basic ' + base64.b64encode(('vrcx:' + PASSWORD).encode()).decode()}


def test_backup_get_never_creates_files_even_with_the_legacy_create_query(gateway_http):
    server, state = gateway_http
    assert request(server, '/api/backup?op=create')[0] == 401
    headers = {**access(), 'Origin': 'https://cross-site.example.invalid',
               'Sec-Fetch-Site': 'cross-site'}
    for path in ('/api/backup', '/api/backup?op=list', '/api/backup?op=create'):
        status, _, payload = request(server, path, headers=headers)
        assert status == 200 and json.loads(payload) == {'backups': []}
    assert not (state / 'backups').exists()


def test_backup_post_requires_auth_and_same_site_then_creates_valid_sqlite(gateway_http):
    server, state = gateway_http
    body = json.dumps({'op': 'create'}).encode()
    assert request(server, '/api/backup-op', 'POST', body=body)[0] == 401
    for foreign in ({'Origin': 'https://cross-site.example.invalid'}, {'Sec-Fetch-Site': 'cross-site'}):
        assert request(server, '/api/backup-op', 'POST', {**access(), **foreign}, body)[0] == 403
    assert not (state / 'backups').exists()
    host = '127.0.0.1:' + str(server.server_address[1])
    status, _, payload = request(server, '/api/backup-op', 'POST',
                                 {**access(), 'Origin': 'http://' + host}, body)
    result = json.loads(payload)
    assert status == 200 and result['ok'] is True
    with sqlite3.connect(state / 'backups' / result['file']) as connection:
        assert connection.execute('SELECT value FROM example').fetchall() == [(7,)]
        assert connection.execute('PRAGMA integrity_check').fetchone() == ('ok',)
    status, _, payload = request(server, '/api/backup?op=create', headers=access())
    assert status == 200 and json.loads(payload) == {'backups': [result['file']]}
    assert [p.name for p in (state / 'backups').iterdir()] == [result['file']]


@pytest.fixture
def upstream_http(account_http, monkeypatch):
    server, state = account_http
    root = state / 'upstream-dist'
    root.mkdir()
    (root / 'index.html').write_text('synthetic index')
    (root / 'assets').mkdir()
    (root / 'assets' / 'app.js').write_bytes(b'const synthetic = 7;\n' * 100)
    (root / 'nested').mkdir()
    (root / 'nested' / 'index.html').write_text('synthetic nested index')
    sibling = state / 'upstream-dist-private'
    sibling.mkdir()
    (sibling / 'fixture.txt').write_text('synthetic outside fixture')
    monkeypatch.setattr(web, '_find_upstream_dist', lambda: str(root))
    return server, root, sibling


def test_upstream_keeps_auth_normal_files_directory_indexes_and_gzip(upstream_http):
    server, root, _ = upstream_http
    assert request(server, '/upstream/')[0] == 401
    for path, expected in (('/upstream/', b'synthetic index'),
                           ('/upstream/nested/', b'synthetic nested index')):
        status, _, body = request(server, path, headers={'X-Web-Token': TOKEN})
        assert status == 200 and body == expected
    status, headers, body = request(server, '/upstream/assets/app.js',
                                    headers={'X-Web-Token': TOKEN, 'Accept-Encoding': 'gzip'})
    assert status == 200 and headers['Content-Encoding'] == 'gzip'
    assert gzip.decompress(body) == (root / 'assets/app.js').read_bytes()
    assert request(server, '/upstream/missing.js', headers={'X-Web-Token': TOKEN})[0] == 404


def test_upstream_rejects_same_prefix_sibling_and_parent_paths(upstream_http):
    server, _, _ = upstream_http
    for path in ('/upstream/../upstream-dist-private/fixture.txt',
                 '/upstream/nested/../../upstream-dist-private/fixture.txt'):
        status, _, body = request(server, path, headers={'X-Web-Token': TOKEN})
        assert status == 403
        assert b'synthetic outside fixture' not in body


@pytest.mark.parametrize('kind', ['file', 'directory', 'index'])
def test_upstream_rejects_symlinks_leaving_the_static_root(upstream_http, kind):
    server, root, sibling = upstream_http
    if kind == 'file':
        link, target, path = root / 'linked.txt', sibling / 'fixture.txt', '/upstream/linked.txt'
    elif kind == 'directory':
        link, target, path = root / 'linked', sibling, '/upstream/linked/fixture.txt'
    else:
        (root / 'linked-index').mkdir()
        link, target, path = root / 'linked-index/index.html', sibling / 'fixture.txt', '/upstream/linked-index/'
    try:
        link.symlink_to(target, target_is_directory=kind == 'directory')
    except OSError:
        pytest.skip('当前系统不允许创建测试软链')
    status, _, body = request(server, path, headers={'X-Web-Token': TOKEN})
    assert status == 403 and b'synthetic outside fixture' not in body


def test_upstream_allows_a_symlink_resolving_inside_the_static_root(upstream_http):
    server, root, _ = upstream_http
    try:
        (root / 'alias.html').symlink_to(root / 'index.html')
    except OSError:
        pytest.skip('当前系统不允许创建测试软链')
    status, _, body = request(server, '/upstream/alias.html', headers={'X-Web-Token': TOKEN})
    assert status == 200 and body == b'synthetic index'
