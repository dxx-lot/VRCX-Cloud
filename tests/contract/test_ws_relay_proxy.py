'WS 实时管线代理接线 · 契约测试\n\n背景：VRChat 流量改走服务器 SSH SOCKS5 隧道（127.0.0.1:1080）。\nREST 侧 requests 原生吃 config.proxy（pysocks），WS 侧此前 connect() 不带代理参数、\n永远直连——本切片让 WS 与 REST 共用同一开关。\n\n上游/库依据：\n- websocket-client 1.9 的 connect(proxy=...) 统一代理参数；\n- websocket/_http.py 原生识别 socks5h（DNS 一并在代理侧解析）；\n- requests + pysocks：socks5h:// 直接可用（requests[socks]）。'










import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src" / "webui"))

import vrc_watch


def test_ws_proxy_kw_none_means_direct():
    vrc_watch.PROXIES = None
    assert vrc_watch._ws_proxy_kw() == {}


def test_ws_proxy_kw_socks5h_old_style():
    """websocket-client 1.9 的 proxy=URL 参数是坏的（proxy_info 只认老式键），
    所以这里必须产出 http_proxy_host/proxy_type 形态；socks5h 走 python-socks 且 DNS 在代理侧。"""
    url = "socks5h://127.0.0.1:1080"
    vrc_watch.PROXIES = {"http": url, "https": url}
    assert vrc_watch._ws_proxy_kw() == {
        "proxy_type": "socks5h",
        "http_proxy_host": "127.0.0.1",
        "http_proxy_port": 1080,
    }


def test_ws_proxy_kw_http_with_auth():
    vrc_watch.PROXIES = {"http": "http://u:p@10.0.0.1:3128",
                         "https": "http://u:p@10.0.0.1:3128"}
    assert vrc_watch._ws_proxy_kw() == {
        "proxy_type": "http",
        "http_proxy_host": "10.0.0.1",
        "http_proxy_port": 3128,
        "http_proxy_auth": ("u", "p"),
    }


def test_ws_proxy_kw_empty_value_means_direct():
    vrc_watch.PROXIES = {"https": ""}
    assert vrc_watch._ws_proxy_kw() == {}


def test_ws_connect_call_site_wires_proxy_kw():
    """防回退：ws.connect 调用点必须带 **_ws_proxy_kw()（漏接=WS 永远直连）。"""
    src = (Path(__file__).resolve().parents[2] / "src" / "webui" / "vrc_watch.py").read_text(encoding="utf-8")
    assert "timeout=15, **_ws_proxy_kw()" in src
