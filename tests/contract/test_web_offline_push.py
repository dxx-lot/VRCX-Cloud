'网页下线独立推送 · 仿真契约测试\n\n驱动真实 watch() 状态机（sim_common 骨架）：\n- 网页在线（state=active）好友消失 → ⚪"网页下线了"（独立开关 notify_active_offline，\n  默认开；关掉则不推）；\n- 游戏内好友消失 → 🔴"下线了"（notify_offline 老语义不变）；\n两条路径互不串扰。'







import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sim_common


def _with_toggle(flag):
    """包一层 write_cfg：write 后追加 notify_active_offline 开关"""
    orig = sim_common.write_cfg

    def wrapped(watch_list=(), **over):
        orig(watch_list, **over)
        p = sim_common.vrc_watch.CONFIG_PATH
        cfg = json.load(open(p, encoding="utf-8"))
        cfg["notify_active_offline"] = flag
        json.dump(cfg, open(p, "w", encoding="utf-8"), ensure_ascii=False)

    sim_common.write_cfg = wrapped
    return orig


def _titles(pushes):
    return pushes[::2]  # run() 里 title/body 交替 append，标题在偶数位


def test_web_active_friend_gone_pushes_web_offline(monkeypatch):
    orig = _with_toggle(True)
    rounds = [([], [sim_common.fr("usr_w1", "网页仔", location="")]),
              ([], []), ([], [])]
    pushes, _ = sim_common.run(rounds, watch_list=["网页仔"])
    titles = _titles(pushes)
    assert any("网页下线" in t and "🟠" in t for t in titles), titles
    assert not any("🔴" in t for t in titles), "网页下线不应走游戏下线文案"
    sim_common.write_cfg = orig


def test_web_active_toggle_off_silences(monkeypatch):
    orig = _with_toggle(False)
    rounds = [([], [sim_common.fr("usr_w1", "网页仔", location="")]),
              ([], []), ([], [])]
    pushes, _ = sim_common.run(rounds, watch_list=["网页仔"])
    assert not any("网页下线" in t for t in _titles(pushes)), _titles(pushes)
    sim_common.write_cfg = orig


def test_game_friend_gone_keeps_legacy_offline_push(monkeypatch):
    orig = _with_toggle(True)
    rounds = [([], [sim_common.fr("usr_g1", "游戏仔", location="wrld_x:1")]),
              ([], []), ([], [])]
    pushes, _ = sim_common.run(rounds, watch_list=["游戏仔"])
    titles = _titles(pushes)
    assert any("🔴" in t and "下线" in t for t in titles), titles
    assert not any("网页下线" in t for t in titles), "游戏下线不应走网页文案"
    sim_common.write_cfg = orig
