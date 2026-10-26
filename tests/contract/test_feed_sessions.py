"""Correct contaminated current/read models without rewriting historical events."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src/webui'))
from services.feed import FeedRepository
from services.presence import confirmed_session_start


def database(tmp_path):
    path=tmp_path/'events.db'
    conn=sqlite3.connect(path)
    conn.execute('CREATE TABLE events(id INTEGER PRIMARY KEY,friend_id TEXT,event TEXT,ts INTEGER,duration INTEGER,prev_state TEXT)')
    conn.execute('CREATE INDEX events_friend ON events(friend_id,ts)')
    conn.executemany('INSERT INTO events VALUES(?,?,?,?,?,?)',[
        (1,'usr_one','active',0,None,None),(2,'usr_one','online',21586,None,'active'),
        (3,'usr_one','offline',62340,62340,'online'),
        (4,'usr_web','active',60000,None,None),(5,'usr_web','offline',62340,2340,'active'),
        (6,'usr_unknown','offline',62340,1234,'online'),
        (7,'usr_gap','online',60000,None,None),(8,'usr_gap','offline',62340,None,'online'),
        (9,'usr_zero','online',62340,None,None),(10,'usr_zero','offline',62340,0,'online')])
    conn.commit()
    return path,conn


def test_game_duration_excludes_earlier_web_period_and_raw_history_is_immutable(tmp_path):
    path,conn=database(tmp_path)
    before=conn.execute('SELECT * FROM events').fetchall()
    rows=FeedRepository(path,lambda _:('', '', '')).read()['events']
    one=next(e for e in rows if e['id']==3)
    assert one['duration']==62340 and one['session_duration']==40754
    assert one['duration_source']=='transition'
    assert conn.execute('SELECT * FROM events').fetchall()==before
    conn.close()


def test_web_zero_and_missing_history_have_distinct_projections(tmp_path):
    path,conn=database(tmp_path)
    rows={e['id']:e for e in FeedRepository(path,lambda _:('', '', '')).read()['events']}
    assert rows[5]['session_duration']==2340 and rows[10]['session_duration']==0
    assert rows[6]['session_duration'] is None and rows[8]['session_duration'] is None
    assert rows[6]['duration']==1234
    conn.close()


def test_start_reconcile_uses_latest_matching_transition_only(tmp_path):
    _,conn=database(tmp_path)
    assert confirmed_session_start(conn,'usr_one','online',0,60000)==21586
    assert confirmed_session_start(conn,'usr_one','online',0,63000)==0  # Departed: do not invent a new session.
    assert confirmed_session_start(conn,'usr_one','active',0,60000)==0
    assert confirmed_session_start(conn,'usr_one','online',30000,60000)==30000
    assert confirmed_session_start(conn,'unknown','online',100,60000)==100
    conn.close()


def test_feed_reports_last_successful_collection_without_changing_database(tmp_path):
    path,conn=database(tmp_path)
    conn.execute('CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT)')
    conn.execute("INSERT INTO meta VALUES('last_sync','1700000000')")
    conn.commit()
    before=conn.execute('SELECT * FROM meta').fetchall()
    conn.close()

    payload=FeedRepository(path,lambda _:('', '', '')).read()
    assert payload['last_sync']==1700000000
    assert payload['server_now']>=1700000000
    with sqlite3.connect(path) as verify:
        assert verify.execute('SELECT * FROM meta').fetchall()==before


def test_feed_handles_invalid_collection_metadata(tmp_path):
    path,conn=database(tmp_path)
    conn.execute('CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT)')
    conn.execute("INSERT INTO meta VALUES('last_sync','not-a-time')")
    conn.commit()
    conn.close()
    assert FeedRepository(path,lambda _:('', '', '')).read()['last_sync'] is None


def test_history_filters_friend_and_name_before_the_global_row_limit(tmp_path):
    path,conn=database(tmp_path)
    conn.execute('ALTER TABLE events ADD COLUMN display_name TEXT')
    conn.execute('DELETE FROM events')
    rows=[]
    for index in range(530):
        target=index<30 or index>=523
        rows.append((index+1,'usr_target' if target else 'usr_other',
                     'FixtureFriend' if target else 'Other','online',1700000000+index))
    conn.executemany('INSERT INTO events(id,friend_id,display_name,event,ts) VALUES(?,?,?,?,?)',rows)
    conn.commit()
    before=conn.execute('SELECT COUNT(*) FROM events').fetchone()[0]
    conn.close()

    repository=FeedRepository(path,lambda _:('', '', ''))
    recent=repository.read()['events']
    assert len(recent)==500
    assert sum(event['friend_id']=='usr_target' for event in recent)==7
    for filters in ({'friend_id':'usr_target'},{'name':'FixtureFriend'}):
        scoped=repository.read(since=1700000000,**filters)['events']
        assert len(scoped)==37
        assert all(event['friend_id']=='usr_target' for event in scoped)
        assert scoped[0]['id']==530 and scoped[-1]['id']==1
    with sqlite3.connect(path) as verify:
        assert verify.execute('SELECT COUNT(*) FROM events').fetchone()[0]==before
