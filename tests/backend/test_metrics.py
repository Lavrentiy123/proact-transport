"""BE-8 (A5): /metrics в формате Prometheus."""

import re
import socket
import time

from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.hub import StubHub
from backend.app.live import LiveHub
from backend.app.main import create_app
from backend.app.ndtp.codec import encode_handshake, encode_nav
from features import to_epoch_s

LINE = re.compile(r'^[a-z_]+(\{[a-z_]+="[^"]*"\}|_count)? -?[0-9.e+-]+$')


def _check_format(text):
    for ln in text.strip().splitlines():
        assert ln.startswith("# ") or LINE.match(ln), ln


def test_metrics_live():
    hub = LiveHub(Settings(ndtp_port=0, ml_url=""))
    with TestClient(create_app(hub=hub, ws_period_s=0.05)) as c:
        t0 = int(to_epoch_s("2026-01-06 06:58:00"))
        with socket.create_connection(("127.0.0.1", hub.server.port)) as s:
            s.sendall(encode_handshake(985940, 1))
            for i in range(5):
                s.sendall(encode_nav(985940, i + 2, t0 + 10 * i, 55.66, 37.55, 20, 90, True))
            deadline = time.time() + 5
            while hub.server.realtime_packets < 5 and time.time() < deadline:
                time.sleep(0.05)
            text = c.get("/metrics").text
        _check_format(text)
        for name in ("ndtp_packets_total 5", "ndtp_crc_errors_total 0", "ndtp_sessions 1", "ws_clients 0",
                     'dropped_total{kind="out_of_window"} 0', 'backend_mode{mode="LIVE"} 1'):
            assert name in text, name
        assert 'tick_duration_ms{quantile="0.99"}' in text or "tick_duration_ms_count 0" in text


def test_metrics_stub():
    with TestClient(create_app(hub=StubHub(), ws_period_s=0.05)) as c:
        text = c.get("/metrics").text
    _check_format(text)
    assert "backend_stub 1" in text and "ws_clients 0" in text
