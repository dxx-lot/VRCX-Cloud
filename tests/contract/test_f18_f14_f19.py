"""F-18/F-14/F-19 契约测试

- F-18 状态预设（上游 useStatusPresets.js：本地存储、MAX 10、去重、删除）
- F-14 群组详情（上游 group.js getGroup：GET groups/{id}）
- F-19 服务状态（上游 vrcStatus.js：status.vrchat.com/api/v2/status.json，
  'All Systems Operational' = 无故障；major = 严重）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import pytest

from status_presets import StatusPresetStore
from vrc_status import parse_status_json


# ---------- F-18 状态预设 ----------

def test_preset_roundtrip(tmp_path):
    s = StatusPresetStore(db_path=tmp_path / "db.sqlite")
    s.add("join me", "来玩")
    assert s.list() == [{"status": "join me", "desc": "来玩"}]


def test_preset_max10(tmp_path):
    s = StatusPresetStore(db_path=tmp_path / "db.sqlite")
    for i in range(10):
        assert s.add("busy", f"状态{i}") == "ok"
    assert s.add("busy", "第11个") == "limit"


def test_preset_dedupe(tmp_path):
    s = StatusPresetStore(db_path=tmp_path / "db.sqlite")
    assert s.add("join me", "来玩") == "ok"
    assert s.add("join me", "来玩") == "exists"


def test_preset_remove(tmp_path):
    s = StatusPresetStore(db_path=tmp_path / "db.sqlite")
    s.add("join me", "来玩")
    s.remove(0)
    assert s.list() == []


def test_preset_persist_across_instances(tmp_path):
    s1 = StatusPresetStore(db_path=tmp_path / "db.sqlite")
    s1.add("busy", "勿扰中")
    s2 = StatusPresetStore(db_path=tmp_path / "db.sqlite")
    assert s2.list() == [{"status": "busy", "desc": "勿扰中"}]


# ---------- F-19 服务状态 ----------

def test_status_all_operational():
    data = {"status": {"indicator": "none", "description": "All Systems Operational"},
            "page": {"updated_at": "2026-09-29T12:00:00Z"}}
    out = parse_status_json(data)
    assert out["issue"] is False and out["summary"] == "" and out["indicator"] == "none"


def test_status_major_outage():
    data = {"status": {"indicator": "major", "description": "Login issues"},
            "page": {"updated_at": "2026-09-29T12:00:00Z"}}
    out = parse_status_json(data)
    assert out["issue"] is True and out["indicator"] == "major"
    assert out["summary"] == "Login issues"


# ---------- F-14 群组详情 ----------

class FakeResponse:
    def __init__(self, status, j):
        self.status_code = status
        self._j = j
    def json(self):
        return self._j


class FakeTransport:
    """requests.Session 形状（生产一致）：返回 Response 对象"""
    def __init__(self, script):
        self.script = script

    def get(self, path, headers=None, params=None, **kw):
        base = path.split("?")[0]
        for k, v in self.script.items():
            if base.endswith(k):
                return FakeResponse(v[0], v[1])
        return FakeResponse(404, {})


def test_group_detail_passthrough():
    from group_client import get_group
    fixture = {"id": "grp_1", "name": "China", "memberCount": 14691,
               "description": "群组描述", "visibility": "public",
               "joining": False, "createdAt": "2021-01-01T00:00:00Z"}
    c = FakeTransport({"groups/grp_1": (200, fixture)})
    g = get_group(c, "grp_1")
    assert g["name"] == "China" and g["memberCount"] == 14691
