"""Real Requests Session/Response transport: byte cache and account capabilities."""
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src/webui'))
import web
from services.media import MediaCache, NoPasswordAuth, validate_url

PNG=b'\x89PNG\r\n\x1a\n'+b'fixture'*10
URL='https://api.vrchat.cloud/api/1/file/file_fixture/1/file'


def session(calls,body=PNG,status=200,headers=None,delay=None):
    transport=requests.Session()
    def get(url,**options):
        calls.append((url,options))
        if delay: delay()
        response=requests.Response();response.status_code=status
        response._content=body;response._content_consumed=True
        response.headers.update(headers or {})
        return response
    transport.get=get
    return transport


def test_cache_serves_real_bytes_after_restart_without_a_network_factory(tmp_path):
    calls=[];cache=MediaCache(tmp_path/'cache')
    cold=cache.get('A',URL,lambda:session(calls))
    assert not cold['cached'] and len(calls)==1
    assert cache.read('A',cold['src'])==(PNG,'image/png')
    assert 'stream' in calls[0][1] and not calls[0][1]['allow_redirects']
    restarted=MediaCache(tmp_path/'cache')
    warm=restarted.get('A',URL,lambda:pytest.fail('warm cache went to VRChat'))
    assert warm['cached'] and restarted.read('A',warm['src'])[0]==PNG
    assert restarted.read('A',cold['src']) is None
    assert (tmp_path/'cache').stat().st_mode&0o777==0o700
    assert all(p.stat().st_mode&0o777==0o600 for p in (tmp_path/'cache').iterdir())


def test_cache_capability_is_isolated_by_account_and_not_a_raw_url(tmp_path):
    cache=MediaCache(tmp_path);ticket=cache.get('A',URL,lambda:session([]))
    assert cache.read('B',ticket['src']) is None
    assert 'file_fixture' not in ticket['src']
    assert cache.read('A','/media/../../config.json') is None


@pytest.mark.parametrize('url',[
    'http://api.vrchat.cloud/api/1/file/x','https://localhost/image',
    'https://api.vrchat.cloud/api/1/auth/user','https://api.vrchat.cloud/api/1/users/usr_one',
    'https://user:password@api.vrchat.cloud/api/1/file/x',
    'https://api.vrchat.cloud:8443/api/1/file/x','https://api.vrchat.cloud/api/1/file/x#fragment'])
def test_rejects_non_image_destinations_before_any_request(url,tmp_path):
    with pytest.raises(ValueError):
        MediaCache(tmp_path).get('A',url,lambda:pytest.fail('invalid destination requested'))


def test_redirect_host_is_revalidated_and_html_and_large_files_are_not_cached(tmp_path):
    calls=[];cache=MediaCache(tmp_path/'redirect')
    with pytest.raises(ValueError):
        cache.get('A',URL,lambda:session(calls,status=302,headers={'Location':'http://127.0.0.1/private'}))
    assert len(calls)==1
    for i,(body,headers) in enumerate([(b'<html>login</html>',{}),(PNG,{'Content-Length':'1000'}),(PNG,{})]):
        folder=tmp_path/str(i)
        with pytest.raises(ValueError):MediaCache(folder,max_file=16).get('A',URL,lambda:session([],body=body,headers=headers))
        assert not folder.exists()


def test_network_auth_strips_password_header_and_keeps_only_domain_bound_cookies():
    s=requests.Session();s.auth=('name','password')
    s.cookies.set('auth','fixture',domain='api.vrchat.cloud',path='/')
    own=s.prepare_request(requests.Request('GET',URL,auth=NoPasswordAuth(),headers={'Authorization':'Basic fixture'}))
    cdn=s.prepare_request(requests.Request('GET','https://assets.vrchat.com/p.png',auth=NoPasswordAuth()))
    assert 'Authorization' not in own.headers and 'auth=fixture' in own.headers['Cookie']
    assert 'Authorization' not in cdn.headers and 'Cookie' not in cdn.headers


def test_simultaneous_same_image_downloads_are_coalesced(tmp_path):
    cache=MediaCache(tmp_path);started=threading.Event();release=threading.Event();calls=[]
    def delay():started.set();assert release.wait(3)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(cache.get,'A',URL,lambda:session(calls,delay=delay))
        assert started.wait(3)
        second=pool.submit(cache.get,'A',URL,lambda:session(calls,delay=delay))
        release.set();assert first.result(3)['src']==second.result(3)['src']
    assert len(calls)==1


def test_bounded_lru_and_symlink_directory(tmp_path):
    cache=MediaCache(tmp_path/'cache',max_files=2,max_bytes=2*len(PNG))
    for i in range(4):cache.get('A',URL+str(i),lambda:session([]))
    files=list(cache.root.iterdir());assert len(files)==2 and sum(p.stat().st_size for p in files)<=2*len(PNG)
    alias=tmp_path/'alias';alias.symlink_to(cache.root,target_is_directory=True)
    unsafe=MediaCache(alias)
    assert not unsafe._read(files[0].name)
    with pytest.raises(ValueError):unsafe.get('A',URL,lambda:session([]))


def test_failed_downloads_do_not_retry_repeatedly_for_the_same_account(tmp_path):
    cache=MediaCache(tmp_path);calls=[]
    for _ in range(3):
        with pytest.raises(ValueError):cache.get('A',URL,lambda:session(calls,status=403))
    assert len(calls)==1
    with pytest.raises(ValueError):cache.get('B',URL,lambda:session(calls,status=403))
    assert len(calls)==2


def test_binary_http_route_requires_valid_ticket_and_json_route_requires_web_auth(tmp_path,monkeypatch):
    from http.server import ThreadingHTTPServer
    auth=tmp_path/'auth.json';auth.write_text('{}')
    monkeypatch.setattr(web,'DB_PATH',str(tmp_path/'db.sqlite'))
    monkeypatch.setattr(web,'AUTH_PATH',str(auth))
    monkeypatch.setattr(web,'load_config',lambda:{'web_password':'fixture'})
    cache=web._image_cache();ticket=cache.get(web._image_scope(),URL,lambda:session([]))
    server=ThreadingHTTPServer(('127.0.0.1',0),web.Handler)
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    try:
        base='http://127.0.0.1:'+str(server.server_port)
        r=requests.get(base+ticket['src'],timeout=3)
        assert r.status_code==200 and r.content==PNG and r.headers['Content-Type']=='image/png'
        assert r.headers['Cache-Control'].startswith('private') and r.headers['X-Content-Type-Options']=='nosniff'
        assert requests.get(base+'/api/image',timeout=3).status_code==401
        assert requests.get(base+ticket['src']+'?url=ignored',timeout=3).status_code==404
        auth.write_text('{"revision":2}')
        assert requests.get(base+ticket['src'],timeout=3).status_code==404
    finally:
        server.shutdown();server.server_close();worker.join(3)


def test_api_image_scope_changes_and_peer_ticket_rewriting(tmp_path,monkeypatch):
    auth=tmp_path/'auth.json';auth.write_text('{}')
    monkeypatch.setattr(web,'DB_PATH',str(tmp_path/'db.sqlite'))
    monkeypatch.setattr(web,'AUTH_PATH',str(auth))
    monkeypatch.setattr(web,'load_config',lambda:{'peer_url':'http://127.0.0.1:8001'})
    calls=[];monkeypatch.setattr(web,'VRChatClient',lambda cfg:SimpleNamespace(s=session(calls)))
    first=web.api_image({'url':[URL]});assert web.api_image({'url':[URL]})['cached']
    auth.write_text('{"revision":2}')
    assert web._image_cache().read(web._image_scope(),first['src']) is None
    response=requests.Response();response.status_code=200
    response._content=__import__('json').dumps(first).encode()
    monkeypatch.setattr(web.requests,'get',lambda *a,**kw:response)
    peer=web.api_peer_relay_get('/api/image?url='+URL)
    assert peer['src'].startswith('/media/peer/')
