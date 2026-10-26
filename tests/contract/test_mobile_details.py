"""Real transport shapes; fast reads, lazy partitions, complete room identity."""
import json
import sqlite3
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src' / 'webui'))
import web
import vrc_watch
from services.presence import PresenceGate, state_of
from services.worlds import rooms_for_world


@pytest.fixture
def database(monkeypatch, tmp_path):
    db_path = str(tmp_path / 'vrc_watch.db')
    auth = str(tmp_path / 'auth-ui.json')
    Path(auth).write_text('{}')
    monkeypatch.setattr(vrc_watch, 'DB_PATH', db_path)
    monkeypatch.setattr(web, 'DB_PATH', db_path)
    monkeypatch.setattr(web, 'AUTH_PATH', auth)
    conn = vrc_watch.init_db()
    conn.execute("INSERT INTO friends_all(friend_id,display_name,in_roster) VALUES ('usr_one','One',1)")
    conn.execute("INSERT INTO worlds VALUES ('wrld_one','World',1)")
    conn.commit();conn.close()
    web._invalidate_session()
    monkeypatch.setattr(web, 'load_config', lambda: {})
    return db_path


def transport(monkeypatch, payloads):
    calls = []
    session = requests.Session()
    def get(url, **kwargs):
        suffix = url[len(web.BASE):]
        calls.append((suffix,kwargs))
        value = payloads[suffix]  # Unexpected eager requests fail immediately.
        response = requests.Response();response.status_code = 200
        response._content = json.dumps(value).encode()
        return response
    session.get = get
    monkeypatch.setattr(web, 'VRChatClient', lambda cfg: SimpleNamespace(s=session,_web_epoch=web._ensure_scope()))
    return calls


def test_world_read_is_local_and_never_fans_out_or_calls_peer(database,monkeypatch):
    callbacks = []
    monkeypatch.setattr(web._REFRESHER,'submit',lambda key,fn: callbacks.append(fn))
    monkeypatch.setattr(web,'VRChatClient',lambda cfg: pytest.fail('world snapshot waited on network'))
    start=time.monotonic();result=web.api_world({'id':['wrld_one']})
    assert time.monotonic()-start < .2
    assert result['world']['name']=='World' and result['stale']
    assert result['pub_online'] is None and len(callbacks)==1


def test_rooms_keep_full_identity_and_unknown_occupancy():
    one='wrld_one:7~hidden(usr_one)~region(eu)~nonce(secret1)'
    two='wrld_one:7~friends(usr_two)~region(us)~nonce(secret2)'
    rooms=rooms_for_world({'id':'wrld_one','instances':[['8~region(jp)',12]]},
                          [{'name':'One','location':one},{'name':'Two','location':two}],vrc_watch.parse_location)
    assert len(rooms)==3 and {r['location'] for r in rooms}=={one,two,'wrld_one:8~region(jp)'}
    assert [r['count'] for r in rooms]==[12,None,None]


def test_instance_snapshot_is_fast_and_refresh_keeps_full_access_tag(database,monkeypatch):
    loc='wrld_one:7~hidden(usr_one)~region(eu)~nonce(secret)'
    jobs=[];monkeypatch.setattr(web._REFRESHER,'submit',lambda key,fn: jobs.append(fn))
    calls=transport(monkeypatch,{'/instances/'+loc:{'userCount':7,'capacity':20,'queueSize':2}})
    result=web.api_instance({'location':[loc]})
    assert calls==[] and result['live'] is None
    jobs.pop()()
    result=web.api_instance({'location':[loc]})
    assert calls[0][0]=='/instances/'+loc
    assert result['live']['user_count']==7 and result['live']['queue_size']==2


def test_cold_profile_only_fetches_profile_not_all_dialog_tabs(database,monkeypatch):
    calls=transport(monkeypatch,{'/users/usr_one':{'id':'usr_one','displayName':'One','bio':'Biography','tags':[]}})
    result=web._friend_live('usr_one')
    assert [c[0] for c in calls]==['/users/usr_one']
    assert result['user']['bio']=='Biography' and result['loaded_sections']==['profile']


def test_partial_profile_keeps_list_photo_and_existing_photo_fields(database,monkeypatch):
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE friends_all SET thumb='https://example.test/roster.png'")
    transport(monkeypatch,{'/users/usr_one':{'id':'usr_one','displayName':'One','tags':[]}})
    result=web._friend_live('usr_one')
    assert result['user']['currentAvatarThumbnailImageUrl']=='https://example.test/roster.png'
    assert result['user']['_avatar_fallback']=='https://example.test/roster.png'
    transport(monkeypatch,{'/users/usr_one':{'id':'usr_one','displayName':'One','tags':[], 'currentAvatarThumbnailImageUrl':''}})
    result=web._friend_live('usr_one')
    assert result['user']['currentAvatarThumbnailImageUrl']==''
    assert result['user']['_avatar_fallback']=='https://example.test/roster.png'


@pytest.mark.parametrize('payload',[{'requiresTwoFactorAuth':['emailOtp']},{'id':'usr_other'},{'error':{'message':'not ready'}}])
def test_invalid_profile_cannot_replace_cached_user_or_photos(database,monkeypatch,payload):
    transport(monkeypatch,{'/users/usr_one':{'id':'usr_one','displayName':'One','tags':[], 'currentAvatarThumbnailImageUrl':'https://example.test/good.png'}})
    before=web._friend_live('usr_one')
    transport(monkeypatch,{'/users/usr_one':payload})
    assert web._friend_live('usr_one').get('error')
    assert web._friend_cache['usr_one'][1]==before


def test_corrupt_persistent_user_identity_falls_back_to_roster(database):
    web._self_cache.update(data={'id':'usr_owner'},ts=time.time())
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE friends_all SET thumb='https://example.test/roster.png'")
        conn.execute('CREATE TABLE user_cache(uid TEXT PRIMARY KEY,payload TEXT,ts REAL)')
        conn.execute('INSERT INTO user_cache VALUES (?,?,?)',('usr_one',json.dumps({'user':{'id':None},'_account_id':'usr_owner','profile_loaded':True}),time.time()))
    result=web._friend_local_payload('usr_one')
    assert result['user']['id']=='usr_one'
    assert result['user']['_avatar_fallback']=='https://example.test/roster.png'


def test_selected_tab_only_loads_its_partition_and_preserves_profile(database,monkeypatch):
    transport(monkeypatch,{'/users/usr_one':{'id':'usr_one','displayName':'One','bio':'Biography','tags':[]}})
    web._friend_live('usr_one')
    calls=transport(monkeypatch,{'/users/usr_one/groups':[{'groupId':'grp_one','name':'Group','isRepresenting':True}]})
    result=web.api_friend_section({'id':['usr_one'],'part':['groups']})
    assert [c[0] for c in calls]==['/users/usr_one/groups']
    assert result['user']['bio']=='Biography' and result['groups'][0]['isRepresenting']


def test_cached_profile_presence_is_updated_from_current_roster(database):
    conn=sqlite3.connect(database)
    conn.execute("INSERT INTO friends_current(friend_id,display_name,online_since,location,state) VALUES ('usr_one','One',10,'private','online')")
    conn.commit();conn.close()
    payload={'user':{'id':'usr_one','state':'offline','location':'','isFriend':True}}
    result=web._local_presence(payload,'usr_one')
    assert result['user']['state']=='online' and result['user']['location']=='private'
    conn=sqlite3.connect(database);conn.execute("DELETE FROM friends_current");conn.execute("UPDATE friends_all SET in_roster=0");conn.commit();conn.close()
    result=web._local_presence(payload,'usr_one')
    assert result['user']['state']=='offline' and result['user']['isFriend'] is False


@pytest.mark.parametrize('location',['private','traveling','wrld_one:7'])
def test_hidden_or_traveling_location_remains_game_presence(location):
    assert state_of({'location':location})=='online'


def test_short_api_gap_and_game_disconnect_do_not_create_false_sessions():
    gate=PresenceGate(30);online={'usr_one':{'state':'online','location':'wrld_one:7'}}
    assert gate.apply(online,100)==online
    assert gate.apply({},115)==online
    assert gate.apply(online,125)==online and not gate.pending
    assert gate.apply({'usr_one':{'state':'active','location':'offline'}},140)==online
    assert gate.apply(online,150)==online and not gate.pending


def test_sustained_web_and_offline_transitions_are_confirmed():
    gate=PresenceGate(30);online={'usr_one':{'state':'online'}};web_only={'usr_one':{'state':'active'}}
    gate.apply(online,100)
    assert gate.apply(web_only,120)==online
    assert gate.apply(web_only,150)==web_only
    assert gate.apply({},160)==web_only
    assert gate.apply({},190)=={}


def test_production_monitor_separates_game_and_web_durations(database,monkeypatch):
    batches=[['game'],['game'],['web'],['web'],['game'],['game'],[],[]]
    index={'value':-1}
    cfg={'watch_favorites':False,'watch_list':['One'],'poll_seconds':15}
    monkeypatch.setattr(vrc_watch,'load_config',lambda:cfg)
    monkeypatch.setattr(vrc_watch,'AUTH_PATH',str(Path(database).with_name('auth-ui.json')))
    monkeypatch.setattr(vrc_watch,'now_ts',lambda:100+index['value']*30)
    monkeypatch.setattr(vrc_watch,'ws_pipeline_thread',lambda *args:None)
    monkeypatch.setattr(vrc_watch,'_wait_wake_or_refresh',lambda wake,delay,last:last)
    original_event=vrc_watch.threading.Event
    def event():
        obj=original_event();obj.wait=lambda timeout=None:False;return obj
    monkeypatch.setattr(vrc_watch.threading,'Event',event)
    notifications=[];monkeypatch.setattr(vrc_watch,'push',lambda cfg,title,body:notifications.append(title))
    class Client:
        def __init__(self,cfg):pass
        def get_friends(self,offline=False):
            if offline:return []
            index['value']+=1
            if index['value']>=len(batches):raise StopIteration
            if not batches[index['value']]:return []
            game=batches[index['value']][0]=='game'
            return [{'id':'usr_one','displayName':'One','location':'wrld_one:7' if game else 'offline','status':'active'}]
        def get_world_name(self,wid,db,cache_only=False):return 'World'
    monkeypatch.setattr(vrc_watch,'VRChatClient',Client)
    conn=sqlite3.connect(database)
    with pytest.raises(StopIteration):vrc_watch.watch(cfg,conn)
    rows=conn.execute("SELECT event,ts,duration,prev_state FROM events WHERE event IN ('offline','online','active') ORDER BY ts,id").fetchall()
    conn.close()
    # game 100 -> confirmed web 190, new game 220 -> confirmed offline 310.
    assert rows==[('offline',190,90,'online'),('active',190,None,'online'),('online',220,None,None),('offline',310,90,'online')]
    assert len([n for n in notifications if '下线了' in n])==2


def test_world_image_survives_restart_but_never_crosses_account(database):
    from services.worlds import save_world
    save_world(database,'usr_owner_a','wrld_one',time.time(),{'id':'wrld_one','name':'Photo World','thumb':'https://example.test/world.png','instances':[]})
    web._self_cache.update(data={'id':'usr_owner_a'},ts=time.time())
    result,stale=web._world_snapshot('wrld_one')
    assert result['thumb'].endswith('/world.png') and not stale
    web._invalidate_session()
    web._self_cache.update(data={'id':'usr_owner_b'},ts=time.time())
    result,stale=web._world_snapshot('wrld_one')
    assert result['thumb']=='' and stale


def test_late_groups_partition_preserves_newer_note_and_moderation(database,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    transport(monkeypatch,{'/users/usr_one':{'id':'usr_one','displayName':'One','bio':'Biography','isFriend':True,'note':'new note','tags':[]}})
    web._friend_live('usr_one')
    entered,release=threading.Event(),threading.Event()
    def client(cfg):
        session=requests.Session()
        def get(url,**kwargs):
            suffix=url[len(web.BASE):]
            if suffix.endswith('/groups'):
                entered.set();assert release.wait(2)
                value=[{'groupId':'grp_one','name':'Group','isRepresenting':True}]
            elif suffix.endswith('/playermoderations'):value=[{'type':'block','moderatedUserId':'usr_one'}]
            else:pytest.fail('Unexpected request '+suffix)
            response=requests.Response();response.status_code=200
            response._content=json.dumps(value).encode();return response
        session.get=get
        return SimpleNamespace(s=session,_web_epoch=web._ensure_scope())
    monkeypatch.setattr(web,'VRChatClient',client)
    with ThreadPoolExecutor(max_workers=1) as executor:
        groups=executor.submit(web._friend_live,'usr_one','groups')
        assert entered.wait(2)
        info=web._friend_live('usr_one','info')
        assert info['user']['note']=='new note'
        release.set();result=groups.result(timeout=2)
    assert result['user']['note']=='new note' and result['user']['is_blocked']
    assert {'info','groups','profile'}<=set(result['loaded_sections'])
    assert result['groups'][0]['name']=='Group'


def test_stats_excludes_current_web_sessions_and_closed_web_duration(database):
    now=time.time()
    with sqlite3.connect(database) as conn:
        conn.execute("INSERT INTO friends_current(friend_id,display_name,online_since,location,state) VALUES ('usr_one','One',?,'offline','active')",(now-3600,))
        conn.execute("INSERT INTO events(friend_id,display_name,event,ts,duration,prev_state) VALUES ('usr_one','One','offline',?,3600,'active')",(now-4000,))
    result=web.api_stats({'days':['7']})
    assert result['friends']==[] and result['daily']==[]


def test_private_presence_clears_previous_world_and_image(database):
    with sqlite3.connect(database) as conn:
        conn.execute("INSERT INTO friends_current(friend_id,display_name,online_since,location,state,status_description) VALUES ('usr_one','One',10,'private','online','current description')")
    result=web._local_presence({'user':{'world':'Old room','world_thumb':'https://old.test/image','id':'usr_one'}},'usr_one')
    assert result['user']['world']=='位于私人房间' and result['user']['world_thumb']==''
    assert result['user']['statusDescription']=='current description'


def test_pending_disconnect_keeps_live_status_and_avatar_changes():
    gate=PresenceGate(30)
    gate.apply({'usr_one':{'state':'online','location':'wrld_one:7','status':'active'}},100)
    held=gate.apply({'usr_one':{'state':'active','location':'offline','status':'busy','avatar':'new.png'}},110)
    assert held['usr_one']['state']=='online' and held['usr_one']['location']=='wrld_one:7'
    assert held['usr_one']['status']=='busy' and held['usr_one']['avatar']=='new.png'


def test_favorite_group_keeps_api_identifier_separate_from_display_name(database,monkeypatch):
    transport(monkeypatch,{'/favorite/groups':[{'id':'fgrp_one','name':'group_1','displayName':'My Group','visibility':'private'}],'/favorites':[]})
    result=web.api_favgroups({'type':['friend']})
    assert result['groups'][0]['name']=='group_1' and result['groups'][0]['displayName']=='My Group'


def test_favorite_group_adapter_uses_upstream_put_not_fictitious_post(database,monkeypatch):
    calls=[];session=requests.Session()
    def request(method,url,**kwargs):
        calls.append((method,url[len(web.BASE)+1:],kwargs))
        response=requests.Response();response.status_code=200;response._content=b'{}';return response
    session.request=request
    monkeypatch.setattr(web,'VRChatClient',lambda cfg:SimpleNamespace(s=session))
    monkeypatch.setattr(web,'get_self',lambda client:{'id':'usr_owner'})
    result=web.api_favgroup_create({'type':'friend','group':'group_1','name':'New Name'})
    assert result['ok']
    assert calls==[('PUT','favorite/group/friend/group_1/usr_owner',{'data':None,'json':{'displayName':'New Name'},'headers':None,'timeout':25})]
    assert web.api_favgroup_create({'type':'friend','name':'Missing slot'})['ok'] is False


def test_unfriend_preserves_local_profile_archive(database,monkeypatch):
    session=requests.Session()
    def delete(url,**kwargs):
        assert url.endswith('/auth/user/friends/usr_one')
        response=requests.Response();response.status_code=200;return response
    session.delete=delete
    monkeypatch.setattr(web,'VRChatClient',lambda cfg:SimpleNamespace(s=session))
    assert web.api_friend_delete({'id':'usr_one'})['ok']
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT display_name,in_roster FROM friends_all WHERE friend_id='usr_one'").fetchone()==('One',0)


def test_note_write_updates_owned_detail_cache_and_restart_mirror(database,monkeypatch):
    web._self_cache.update(data={'id':'usr_owner'},ts=time.time())
    transport(monkeypatch,{'/users/usr_one':{'id':'usr_one','displayName':'One','tags':[]}})
    web._friend_live('usr_one')
    session=requests.Session()
    def post(url,**kwargs):
        assert url==web.BASE+'/userNotes' and kwargs['json']=={'targetUserId':'usr_one','note':'new note'}
        response=requests.Response();response.status_code=200;response._content=b'{}';return response
    session.post=post;monkeypatch.setattr(web,'VRChatClient',lambda cfg:SimpleNamespace(s=session))
    assert web.api_friend_note({'id':'usr_one','note':'new note'})['ok']
    assert web._friend_cache['usr_one'][1]['user']['note']=='new note'
    web._friend_cache.clear()
    assert web._friend_local_payload('usr_one')['user']['note']=='new note'


def test_monitor_ws_partial_messages_do_not_drop_location_or_status(database,monkeypatch):
    shared={};cfg={'watch_favorites':False,'poll_seconds':15}
    monkeypatch.setattr(vrc_watch,'load_config',lambda:cfg)
    monkeypatch.setattr(vrc_watch,'AUTH_PATH',str(Path(database).with_name('auth-ui.json')))
    def pipeline(clients,wake,events):shared['events']=events
    monkeypatch.setattr(vrc_watch,'ws_pipeline_thread',pipeline)
    class Thread:
        def __init__(self,target,args,**kwargs):self.target=target;self.args=args
        def start(self):self.target(*self.args)
    class Event:
        def set(self):pass
        def clear(self):pass
        def is_set(self):return False
        def wait(self,*args):return False
    monkeypatch.setattr(vrc_watch,'threading',SimpleNamespace(Event=Event,Thread=Thread))
    monkeypatch.setattr(vrc_watch,'_wait_wake_or_refresh',lambda wake,delay,last:last)
    index={'value':0}
    class Client:
        def __init__(self,cfg):pass
        def get_friends(self,offline=False):
            if offline:return []
            index['value']+=1
            if index['value']==3:raise StopIteration
            if index['value']==2:
                for message in [{'fid':'usr_one','state':'online','location':'wrld_two:8'},
                                {'fid':'usr_one','status':'busy'}, {'fid':'usr_one','avatar':'new.png'}]:
                    shared['events'].put(message)
            return [{'id':'usr_one','displayName':'One','location':'wrld_one:7','status':'active'}]
        def get_world_name(self,wid,db,cache_only=False):return wid
    monkeypatch.setattr(vrc_watch,'VRChatClient',Client)
    monkeypatch.setattr(vrc_watch,'push',lambda *args:None)
    conn=sqlite3.connect(database)
    with pytest.raises(StopIteration):vrc_watch.watch(cfg,conn)
    assert conn.execute("SELECT location,status,avatar FROM friends_current WHERE friend_id='usr_one'").fetchone()==('wrld_two:8','busy','new.png')
    assert conn.execute("SELECT previous_location FROM events WHERE event='location'").fetchone()[0]=='wrld_one:7'
    conn.close()


def test_nonfriend_profile_without_presence_does_not_invent_web_online(database,monkeypatch):
    transport(monkeypatch,{'/users/usr_stranger':{'id':'usr_stranger','displayName':'Unknown Presence','tags':[]}})
    result=web._friend_live('usr_stranger')
    assert result['user']['state']=='unknown' and result['user']['location']==''


@pytest.mark.parametrize('action,method,path,wire_type,flag,expected',[
    ('block','POST','auth/user/playermoderations','block','is_blocked',True),
    ('mute','POST','auth/user/playermoderations','mute','is_muted',True),
    ('unblock','PUT','auth/user/unplayermoderate','block','is_blocked',False),
    ('unmute','PUT','auth/user/unplayermoderate','mute','is_muted',False),
])
def test_moderation_write_refreshes_the_detail_flag(database,monkeypatch,action,method,path,wire_type,flag,expected):
    web._friend_cache['usr_one']=(time.time(),{'user':{'id':'usr_one','is_blocked':False}})
    session=requests.Session()
    def request(actual_method,url,**kwargs):
        assert actual_method==method and url==web.BASE+'/'+path
        assert kwargs['json']=={'moderated': 'usr_one','type':wire_type}
        response=requests.Response();response.status_code=200;return response
    session.request=request;monkeypatch.setattr(web,'VRChatClient',lambda cfg:SimpleNamespace(s=session))
    assert web.api_moderate({'id':'usr_one','type':action})['ok']
    assert web._friend_cache['usr_one'][1]['user'][flag] is expected


@pytest.mark.parametrize('note',['actual viewer note',None])
def test_info_reads_note_from_real_user_profile_without_fictitious_endpoint(database,monkeypatch,note):
    calls=transport(monkeypatch,{
        '/users/usr_one':{'id':'usr_one','displayName':'One','isFriend':True,'note':note,'tags':[]},
        '/auth/user/playermoderations':[],
    })
    web._friend_live('usr_one')
    result=web.api_friend_section({'id':['usr_one'],'part':['info']})
    assert calls==[('/users/usr_one',{'params':None,'timeout':10}),
                   ('/auth/user/playermoderations',{'params':None,'timeout':10})]
    assert result['user']['note']==(note or '') and 'info' in result['loaded_sections']


def test_late_info_cannot_restore_a_note_saved_after_the_read_started(database,monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    web._self_cache.update(data={'id':'usr_owner'},ts=time.time())
    transport(monkeypatch,{'/users/usr_one':{'id':'usr_one','displayName':'One','note':'old note','tags':[]}})
    web._friend_live('usr_one')
    entered,release=threading.Event(),threading.Event()
    session=requests.Session()
    def get(url,**kwargs):
        assert url==web.BASE+'/auth/user/playermoderations'
        entered.set();assert release.wait(2)
        response=requests.Response();response.status_code=200;response._content=b'[]';return response
    def post(url,**kwargs):
        assert url==web.BASE+'/userNotes'
        response=requests.Response();response.status_code=200;response._content=b'{}';return response
    session.get=get;session.post=post
    monkeypatch.setattr(web,'VRChatClient',lambda cfg:SimpleNamespace(s=session,_web_epoch=web._ensure_scope()))
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending=executor.submit(web._friend_live,'usr_one','info')
        assert entered.wait(2)
        assert web.api_friend_note({'id':'usr_one','note':'saved note'})['ok']
        release.set();result=pending.result(timeout=2)
    assert result['user']['note']==result['raw']['note']=='saved note'
    assert web._friend_cache['usr_one'][1]['user']['note']=='saved note'
