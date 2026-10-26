'推送范围模块 · 契约测试\n\nmode 映射是核心语义（错一位就把推送范围搞反）：\n- all       → watch_favorites=False + watch_list=[]（watch_enabled=False → 全员推送）\n- favorites → watch_favorites=True  + watch_list=[]（旧行为：跟随收藏夹）\n- custom    → watch_favorites=False + watch_list=[ids]（监控 watched() 有 fid 匹配，\n              ID 小写化无副作用——usr_ ID 本身全小写）\n监控每轮热读 config → UI 保存后下一轮即生效。'








import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src" / "webui"))

import pytest

import web


@pytest.fixture()
def cfg_file(monkeypatch, tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"poll_seconds": 30, "watch_favorites": True,
                             "watch_list": ["旧名字"], "bark": {"enabled": False}}),
                 encoding="utf-8")
    monkeypatch.setattr(web, "CONFIG_PATH", str(p))
    monkeypatch.setattr(web, "load_config", lambda: json.load(open(p, encoding="utf-8")))
    return p


def _saved(p):
    return json.load(open(p, encoding="utf-8"))


def test_mode_all_disables_watch(cfg_file):
    r = web.api_push_config_set({"mode": "all", "watch_list": []})
    assert r["ok"] is True
    cfg = _saved(cfg_file)
    assert cfg["watch_favorites"] is False and cfg["watch_list"] == []


def test_mode_favorites_restores_legacy(cfg_file):
    web.api_push_config_set({"mode": "favorites", "watch_list": []})
    cfg = _saved(cfg_file)
    assert cfg["watch_favorites"] is True and cfg["watch_list"] == []


def test_mode_custom_writes_ids_keeps_other_fields(cfg_file):
    ids = ["usr_a", "usr_b"]
    r = web.api_push_config_set({"mode": "custom", "watch_list": ids})
    assert r["ok"] is True
    cfg = _saved(cfg_file)
    assert cfg["watch_favorites"] is False
    assert cfg["watch_list"] == ids
    assert cfg["poll_seconds"] == 30 and cfg["bark"] == {"enabled": False}  # 不误伤其他字段


def test_mode_custom_requires_one_friend(cfg_file):
    r = web.api_push_config_set({"mode": "custom", "watch_list": []})
    assert r["ok"] is False


def test_mode_invalid_rejected(cfg_file):
    r = web.api_push_config_set({"mode": "everything", "watch_list": []})
    assert r["ok"] is False


def test_nav_and_routes_wired():
    root=_REPO / "src" / "webui"
    s="\n".join([*(p.read_text() for p in sorted((root/"static").rglob("*.js"))),
                   (root/"templates"/"index.html").read_text(), (root/"web.py").read_text()])
    assert "['push','','推送']" in s
    assert "/api/push-config" in web.ApiRouter({}).allowed("GET")
    assert "/api/push-config-set" in web.ApiRouter({}).allowed("POST")
    assert "APP.pages.register('push'" in s
    assert "async function savePushCfg()" in s
