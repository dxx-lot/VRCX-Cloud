'推送总闸 · 契约测试\n\npush_enabled=False 时 push() 一票否决（Bark/Telegram 全静默）；\n默认缺省=开启。端到端链路由既有 sim 测试覆盖（本文件单元测 push 闸门本身，'





import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src" / "webui"))

import vrc_watch


def test_push_gate_off_blocks_all_channels(monkeypatch):
    calls = []
    monkeypatch.setattr(vrc_watch, "send_bark", lambda cfg, t, b: calls.append(("bark", t)) or True)
    monkeypatch.setattr(vrc_watch, "send_telegram", lambda cfg, t, b: calls.append(("tg", t)) or True)
    cfg = {"push_enabled": False, "bark": {"enabled": True}, "telegram": {"enabled": True}}
    assert vrc_watch.push(cfg, "T", "B") is False
    assert calls == [], "关闭模式下任何渠道都不应被调用"


def test_push_gate_default_is_on(monkeypatch):
    calls = []
    monkeypatch.setattr(vrc_watch, "send_bark", lambda cfg, t, b: calls.append(("bark", t)) or True)
    cfg = {"bark": {"enabled": True}}   # 无 push_enabled 键 = 默认开启
    assert vrc_watch.push(cfg, "T", "B") is True
    assert len(calls) == 1


def test_push_gate_on_delivers(monkeypatch):
    calls = []
    monkeypatch.setattr(vrc_watch, "send_bark", lambda cfg, t, b: calls.append(("bark", t)) or True)
    cfg = {"push_enabled": True, "bark": {"enabled": True}}
    assert vrc_watch.push(cfg, "T", "B") is True
    assert calls == [("bark", "T")]
