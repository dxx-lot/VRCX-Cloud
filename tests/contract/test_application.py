"""应用入口使用真实本机 HTTP，账号与文件均为临时合成数据。"""
import base64
from contextlib import closing
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import sqlite3
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.application import launcher
from src.application.gateway import Gateway, password_record
from src.application import worker


def test_monitor_waits_for_a_real_saved_session_before_entering_the_engine(tmp_path,monkeypatch):
    path=tmp_path/'auth-ui.json'
    assert not worker.saved_session_available(tmp_path)
    for value in ({},{'cookies':{}},{'cookies':{'auth':''}},{'cookies':{'auth':123}}):
        path.write_text(json.dumps(value),encoding='utf-8')
        assert not worker.saved_session_available(tmp_path)
    calls=[]
    def pause(seconds):
        calls.append(seconds)
        path.write_text(json.dumps({'cookies':{'auth':'synthetic-saved-session'}}),encoding='utf-8')
    monkeypatch.setattr(worker.time,'sleep',pause)
    monkeypatch.setattr(worker.multiprocessing,'parent_process',lambda:None)
    monkeypatch.setattr(worker.sys,'argv',worker.sys.argv.copy())
    monkeypatch.setattr(worker.sys,'path',worker.sys.path.copy())
    monkeypatch.setattr(worker.os,'umask',lambda value:0o077)
    def engine(*args,**kwargs):
        assert calls==[1] and worker.saved_session_available(tmp_path)
        calls.append('engine')
    monkeypatch.setattr(worker.runpy,'run_path',engine)
    monkeypatch.setenv('VRCX_PI_STATE_DIR','synthetic-original')
    monkeypatch.setenv('VRCX_PI_ACCESS_TOKEN_FILE','synthetic-original')
    monkeypatch.setenv('VRCX_PI_MONITOR_PAUSE_FILE','synthetic-original')
    worker.run_worker(str(tmp_path/'runtime'),str(tmp_path),str(tmp_path/'token'),'monitor')
    assert calls==[1,'engine']


def test_private_state_rejects_links_unowned_directories_and_duplicate_processes(tmp_path):
    root = tmp_path/'private'
    launcher.prepare_state(root)
    with launcher.state_lock(root):
        with pytest.raises(ValueError, match='已有应用'):
            with launcher.state_lock(root):
                pass
    target = tmp_path/'unchanged'
    target.write_text('original')
    link = root/'linked.json'
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip('系统不允许当前用户创建符号链接')
    with pytest.raises(ValueError, match='符号链接'):
        launcher.write_json(link, {})
    link.unlink()
    os.link(target, link)
    with pytest.raises(ValueError, match='独立'):
        launcher.write_json(link, {})
    assert target.read_text() == 'original'
    foreign = tmp_path/'foreign'
    foreign.mkdir(); (foreign/'existing').write_text('keep')
    with pytest.raises(ValueError, match='空目录'):
        launcher.prepare_state(foreign)
    if os.name != 'nt':
        assert (root.stat().st_mode & 0o777) == 0o700
        assert ((root/'accounts/a/config.json').stat().st_mode & 0o777) == 0o600


def test_account_transport_configuration_preserves_account_settings(tmp_path):
    launcher.prepare_state(tmp_path)
    path = tmp_path/'accounts/a/config.json'
    config = launcher.read_json(path)
    config.update(proxy='socks5h://127.0.0.1:1080', poll_seconds=45)
    launcher.write_json(path, config)
    listeners = {account: launcher.bind_listener('127.0.0.1', 0) for account in launcher.ACCOUNTS}
    try:
        launcher.configure_accounts(tmp_path, listeners)
        a, b = [launcher.read_json(tmp_path/'accounts'/account/'config.json') for account in launcher.ACCOUNTS]
        assert a['proxy'] == config['proxy'] and a['poll_seconds'] == 45
        assert a['web_port'] != b['web_port']
        assert a['peer_url'] == 'http://127.0.0.1:'+str(b['web_port'])
        assert b['peer_url'] == 'http://127.0.0.1:'+str(a['web_port'])
        assert a['web_bind'] == b['web_bind'] == '127.0.0.1'
        assert not a['push_enabled'] and not b['push_enabled']
    finally:
        for listener in listeners.values(): listener.close()


def test_remote_binding_requires_access_password_and_check_does_not_create_data(tmp_path):
    data = tmp_path/'not-created'
    assert launcher.main(['--data-dir', str(data), '--check']) == 0
    assert not data.exists()
    assert launcher.main(['--data-dir',str(data),'--host','0.0.0.0','--check']) == 1
    assert not data.exists()
    launcher.prepare_state(data)
    with pytest.raises(ValueError, match='访问密码'):
        launcher.serve({'data_dir':data,'host':'0.0.0.0','port':0,'monitor':False}, {'password':None})


@pytest.fixture
def gateway_server():
    release = threading.Event()
    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_GET(self):
            if self.path == '/events':
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                self.wfile.write(b'data: synthetic\n\n');self.wfile.flush();release.wait(3)
                return
            body = b'<html><head></head><body>fixture</body></html>' if self.path == '/' else json.dumps({
                'token':self.headers.get('X-Web-Token'), 'authorization':self.headers.get('Authorization'),
                'cookie':self.headers.get('Cookie')}).encode()
            self.send_response(200);self.send_header('Content-Type','text/html' if self.path=='/' else 'application/json')
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    upstream = ThreadingHTTPServer(('127.0.0.1',0),Upstream)
    threading.Thread(target=upstream.serve_forever,daemon=True).start()
    listener = launcher.bind_listener('127.0.0.1',0)
    gateway = Gateway(listener,upstream.server_address,'synthetic-internal-token')
    threading.Thread(target=gateway.serve_forever,daemon=True).start()
    try:
        yield gateway
    finally:
        release.set();gateway.shutdown();gateway.server_close();upstream.shutdown();upstream.server_close()


def request(server, path='/', method='GET', headers=None, body=None):
    connection = HTTPConnection(*server.server_address,timeout=3)
    connection.request(method,path,headers=headers or {},body=body)
    response = connection.getresponse()
    result = response.status,dict(response.getheaders()),response.read()
    connection.close()
    return result


def test_gateway_strips_browser_credentials_blocks_csrf_and_manages_access_settings(gateway_server):
    server=gateway_server
    status,_,body=request(server,'/inspect',headers={'X-Web-Token':'browser-value','Authorization':'Basic ignored','Cookie':'private=value'})
    assert status == 200
    assert json.loads(body) == {'token':'synthetic-internal-token','authorization':None,'cookie':None}
    assert b'app-access-managed' in request(server)[2]
    assert request(server,'/api/logout','POST',{'Origin':'https://attacker.invalid'},b'{}')[0] == 403
    assert request(server,'/inspect',headers={'Host':'attacker.invalid'})[0] == 403
    assert request(server,'http://attacker.invalid/inspect')[0] == 400
    import socket
    with socket.create_connection(server.server_address,timeout=3) as raw:
        raw.sendall(b'GET http://[invalid HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n')
        assert raw.makefile('rb').readline().split()[1] == b'400'
    assert request(server,'/api/config-set','POST',body=b'{"web_password":"ignored"}')[0] == 400


def test_gateway_auth_covers_html_media_and_api_and_limits_bad_passwords(gateway_server):
    server=gateway_server
    server.password=password_record('synthetic-password-123')
    import struct
    status,headers,icon=request(server,'/icon-192.png')
    assert status == 200 and headers['Content-Type'] == 'image/png'
    assert icon.startswith(b'\x89PNG\r\n\x1a\n') and struct.unpack('>II',icon[16:24]) == (192,192)
    assert json.loads(request(server,'/manifest.webmanifest')[2])['name'] == 'VRCX Cloud'
    for path in ('/','/media/example','/api/status'):
        status,headers,_=request(server,path)
        assert status == 401 and 'WWW-Authenticate' in headers
    authorization='Basic '+base64.b64encode(b'vrcx:synthetic-password-123').decode()
    assert request(server,headers={'Authorization':authorization})[0] == 200
    assert server.password['digest'] != 'synthetic-password-123'
    for _ in range(5): assert request(server)[0] == 401
    assert request(server)[0] == 429


def test_gateway_forwards_sse_immediately_without_waiting_for_the_stream_to_finish(gateway_server):
    connection=HTTPConnection(*gateway_server.server_address,timeout=2)
    started=time.monotonic()
    connection.request('GET','/events')
    response=connection.getresponse()
    assert response.readline() == b'data: synthetic\n'
    assert time.monotonic()-started < 1.5
    connection.close()


def test_real_application_has_one_browser_entry_and_independent_private_accounts(tmp_path):
    state=tmp_path/'app'
    process=subprocess.Popen([sys.executable,'-B',str(ROOT/'run.py'),'--data-dir',str(state),'--port','0','--without-monitor'],
                             cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
    lines=queue.Queue()
    threading.Thread(target=lambda:[lines.put(line) for line in process.stdout],daemon=True).start()
    opener=build_opener(ProxyHandler({}))
    addresses=[]
    try:
        try:
            line=lines.get(timeout=30)
        except queue.Empty:
            process.terminate()
            process.wait(timeout=12)
            logs='\n'.join(path.read_text(encoding='utf-8') for path in state.glob('accounts/*/*.log'))
            pytest.fail('启动失败：'+process.stderr.read()+'\n'+logs)
        assert '已启动' in line,line
        address=line.strip().split('http://',1)[1]
        base='http://'+address
        assert b'app-access-managed' in opener.open(base,timeout=3).read()
        assert json.load(opener.open(base+'api/status',timeout=3))['logged_in'] is False
        assert json.load(opener.open(base+'api/peer-relay?path=%2Fapi%2Fstatus',timeout=3))['logged_in'] is False
        for account in ('a','b'):
            folder=state/'accounts'/account
            config=launcher.read_json(folder/'config.json')
            addresses.append(('127.0.0.1',config['web_port']))
            with pytest.raises(HTTPError) as rejected:
                opener.open('http://127.0.0.1:'+str(config['web_port'])+'/api/status',timeout=3)
            assert rejected.value.code == 401
            with closing(sqlite3.connect(folder/'vrc_watch.db')) as db:
                db.execute('INSERT INTO events(friend_id,display_name,event,ts) VALUES(?,?,?,?)',('usr_'+account,'fixture '+account,'online',time.time()))
                db.commit()
        a=json.load(opener.open(base+'api/feed',timeout=3))['events']
        b=json.load(opener.open(base+'api/peer-relay?path=%2Fapi%2Ffeed',timeout=3))['events']
        assert {row['friend_id'] for row in a} == {'usr_a'}
        assert {row['friend_id'] for row in b} == {'usr_b'}
        assert not (state/'accounts/a/auth-ui.json').exists()
        assert not (state/'accounts/b/auth-ui.json').exists()
    finally:
        process.terminate()
        try: process.wait(timeout=12)
        except subprocess.TimeoutExpired:
            process.kill();process.wait(timeout=3)
        process.stdout.close();process.stderr.close()
    for address in addresses:
        import socket
        deadline=time.monotonic()+5
        while True:
            with socket.socket() as probe:
                closed=probe.connect_ex(address) != 0
            if closed or time.monotonic()>deadline: break
            time.sleep(0.05)
        assert closed
