"""Read/monitor paths must never initiate a password challenge or accept one as a user."""
import json
import sqlite3
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src' / 'webui'))
import vrc_watch
import web


def response(value, status=200):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(value).encode()
    return result


@pytest.mark.parametrize('value,expected', [
    ({'requiresTwoFactorAuth':['emailOtp']}, False), ({}, False), ({'id':'usr_one'}, True),
])
def test_login_status_requires_an_identity_not_just_http200(tmp_path, monkeypatch, value, expected):
    monkeypatch.setattr(vrc_watch, 'AUTH_PATH', str(tmp_path / 'auth-ui.json'))
    client = vrc_watch.VRChatClient({})
    client.s.get = lambda *args, **kwargs: response(value)
    assert client.is_logged_in() is expected


@pytest.mark.parametrize('value', [{'requiresTwoFactorAuth':['emailOtp']}, {}, []])
def test_self_read_rejects_challenge_without_following_users_none(value):
    session = requests.Session()
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        return response(value)
    session.get = get
    assert web._fetch_self(SimpleNamespace(s=session)) is None
    assert calls == [web.BASE + '/auth/user']


def test_saved_credentials_never_authorize_automatic_password_login(monkeypatch):
    client = object.__new__(vrc_watch.VRChatClient)
    client.creds = {'username':'synthetic', 'password':'synthetic-test-only'}
    monkeypatch.setattr(client, 'login', lambda *args, **kwargs: pytest.fail('automatic password challenge'))
    assert client.try_relogin() is False


def test_production_monitor_waits_on_expiry_without_password_challenge(tmp_path, monkeypatch):
    database = tmp_path / 'vrc_watch.db'
    auth = tmp_path / 'auth-ui.json'
    auth.write_text(json.dumps({'credentials': {'username':'synthetic', 'password':'synthetic-test-only'}}))
    original_auth = auth.read_bytes()
    monkeypatch.setattr(vrc_watch, 'DB_PATH', str(database))
    monkeypatch.setattr(vrc_watch, 'AUTH_PATH', str(auth))
    cfg = {'watch_favorites':False, 'poll_seconds':15}
    monkeypatch.setattr(vrc_watch, 'load_config', lambda: cfg)
    monkeypatch.setattr(vrc_watch, 'now_ts', lambda: 100000)
    monkeypatch.setattr(vrc_watch, 'threading', SimpleNamespace(
        Event=threading.Event, Thread=lambda **kwargs: SimpleNamespace(start=lambda:None)))
    def pause(_):
        raise StopIteration
    monkeypatch.setattr(vrc_watch, 'time', SimpleNamespace(time=time.time, sleep=pause))
    monkeypatch.setattr(vrc_watch.VRChatClient, 'login', lambda *args, **kwargs: pytest.fail('monitor initiated login'))
    monkeypatch.setattr(vrc_watch.VRChatClient, 'try_relogin', lambda *args: pytest.fail('monitor invoked automatic relogin'))
    original = vrc_watch.VRChatClient
    calls = []
    class Client(original):
        def __init__(self, config):
            super().__init__(config)
            def get(url, **kwargs):
                calls.append(url)
                return response({'error':{'message':'expired'}}, 401)
            self.s.get = get
    monkeypatch.setattr(vrc_watch, 'VRChatClient', Client)
    monkeypatch.setattr(vrc_watch, 'push', lambda *args: None)
    connection = vrc_watch.init_db()
    with pytest.raises(StopIteration):
        vrc_watch.watch(cfg, connection)
    connection.close()
    assert calls == [vrc_watch.BASE + '/auth/user/friends']
    assert auth.read_bytes() == original_auth
