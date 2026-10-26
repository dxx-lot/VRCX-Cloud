"""F-18 预设接口契约（webui API 形状）"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from status_presets import StatusPresetStore


def test_presets_api_shape(tmp_path):
    """API 返回形状与前端期望一致：[{status, desc}]"""
    s = StatusPresetStore(db_path=tmp_path / "db.sqlite")
    s.add("join me", "来玩")
    assert s.list() == [{"status": "join me", "desc": "来玩"}]


def test_preset_remove_by_index(tmp_path):
    s = StatusPresetStore(db_path=tmp_path / "db.sqlite")
    s.add("busy", "勿扰中")
    s.add("active", "在线")
    s.remove(0)
    assert s.list() == [{"status": "active", "desc": "在线"}]
