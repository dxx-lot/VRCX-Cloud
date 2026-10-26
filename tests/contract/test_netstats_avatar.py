'隧道流量统计 + 用户详情头像兜底 · 契约测试\n\n- _net_windows：左栏流量面板的窗口聚合（今日=本地零点起、1h、24h、实时速率），\n  负增量（ssh 重启计数器归零）必须跳过；\n- _avatar_from_db：VRChat 实时接口对部分用户不回头像 URL，详情页从 friends_all.thumb 兜底。'





import sqlite3
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src" / "webui"))

import pytest

import web


# ---------- _net_windows 聚合 ----------

NOW = 1_800_000_000.0
DAY_START = NOW - 3600 * 5  # 假设 now 是当天凌晨 5 点


def test_net_windows_buckets():
    samples = [
        (NOW - 90000, 100),   # 25h 前 → 只进 total 范围外的会被裁剪，这里 24h 窗口外
        (NOW - 7200, 200),    # 2h 前 → hour24 + today
        (NOW - 1800, 400),    # 30min 前 → hour1 + hour24 + today
        (NOW - 60, 800),      # 1min 前 → 全部窗口
    ]
    w = web._net_windows(samples, now=NOW, day_start=DAY_START)
    assert w["hour24"] == 200 + 400 + 800
    assert w["hour1"] == 400 + 800
    assert w["today"] == 200 + 400 + 800  # 三个样本都在 DAY_START 之后


def test_net_windows_negative_delta_skipped():
    """ssh 重启 → wchar 归零 → 采样出的负增量必须丢弃，不能扣账。"""
    samples = [(NOW - 120, 500), (NOW - 60, -99999), (NOW - 30, 100)]
    w = web._net_windows(samples, now=NOW, day_start=DAY_START)
    assert w["hour24"] == 600 and w["hour1"] == 600


def test_net_windows_rate_is_last_delta():
    samples = [(NOW - 60, 0), (NOW - 30, 300), (NOW - 15, 600)]
    w = web._net_windows(samples, now=NOW, day_start=DAY_START)
    assert w["rate"] == pytest.approx(300 / 15)


def test_net_windows_today_uses_day_start():
    samples = [(DAY_START - 10, 700), (DAY_START + 10, 70)]
    w = web._net_windows(samples, now=NOW, day_start=DAY_START)
    assert w["today"] == 70 and w["hour24"] == 770


# ---------- _avatar_from_db 兜底 ----------

@pytest.fixture()
def friends_db(monkeypatch, tmp_path):
    dbp = tmp_path / "vrc_watch.db"
    conn = sqlite3.connect(dbp)
    conn.execute("CREATE TABLE friends_all (friend_id TEXT, thumb TEXT)")
    conn.execute("INSERT INTO friends_all VALUES ('usr_has', 'https://cdn/x/256')")
    conn.execute("INSERT INTO friends_all VALUES ('usr_empty', '')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(web, "DB_PATH", str(dbp))
    return dbp


def test_avatar_from_db_hit(friends_db):
    assert web._avatar_from_db("usr_has") == "https://cdn/x/256"


def test_avatar_from_db_miss(friends_db):
    assert web._avatar_from_db("usr_unknown") == ""
    assert web._avatar_from_db("usr_empty") == ""


def test_avatar_from_db_bad_path_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(web, "DB_PATH", str(tmp_path / "nope.db"))
    assert web._avatar_from_db("usr_x") == ""
