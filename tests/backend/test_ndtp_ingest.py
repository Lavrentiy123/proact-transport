"""BE-3: TCP-сервер :9201 + приём в реестр ``OnlineVehicle`` (реальный сокет, живое приложение)."""

import socket
import time

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.hub import SystemStatusEx
from backend.app.live import LiveHub
from backend.app.main import create_app
from backend.app.ndtp.codec import encode_handshake, encode_nav
from contracts.schemas import VehicleState
from features import to_epoch_s

KNOWN_UNIT, KNOWN_TR = 985940, 131672      # пара из data/test/traffic.csv, у борта есть расписание
UNKNOWN_UNIT = 1166336                      # unitId из примера спецификации эмулятора, в датасете нет


@pytest.fixture(scope="module")
def live():
    hub = LiveHub(Settings(ndtp_port=0, replay_start_at="2026-01-06T07:00:00", replay_speed=1.0))
    with TestClient(create_app(hub=hub, ws_period_s=0.05)) as client:
        yield client, hub


def _wait(pred, timeout=5.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if pred():
            return True
        time.sleep(0.05)
    return False


def test_ready_and_listening(live):
    client, hub = live
    r = client.get("/ready")
    assert r.status_code == 200, r.text
    assert hub.server.port > 0


def test_ingest_known_unknown_and_bad_crc(live):
    client, hub = live
    t0 = int(to_epoch_s("2026-01-06 06:59:00"))
    with socket.create_connection(("127.0.0.1", hub.server.port)) as s1, \
            socket.create_connection(("127.0.0.1", hub.server.port)) as s2:
        s1.sendall(encode_handshake(KNOWN_UNIT, 1))
        for i in range(10):
            s1.sendall(encode_nav(KNOWN_UNIT, i + 2, t0 + 10 * i, 55.6643 + 0.0001 * i, 37.5536, 20, 90, True))
        s2.sendall(encode_handshake(UNKNOWN_UNIT, 1))
        s2.sendall(encode_nav(UNKNOWN_UNIT, 2, int(time.time()), 55.7030, 37.5030, 30, 180, True))  # метка «сейчас»
        bad = bytearray(encode_nav(KNOWN_UNIT, 99, t0 + 200, 55.67, 37.55, 10, 0, True))
        bad[-1] ^= 0xFF
        s1.sendall(bytes(bad))
        s1.sendall(encode_nav(KNOWN_UNIT, 100, t0 + 210, 55.6655, 37.5536, 15, 90, True))   # после битого — живо
        assert _wait(lambda: hub.server.realtime_packets >= 12), hub.server.realtime_packets
        st = SystemStatusEx.model_validate(client.get("/api/v1/system/status").json())
        assert st.ndtp_sessions == 2
        assert st.ndtp_packets_total == 12 and st.ndtp_crc_errors_total == 1
        assert st.unknown_units == 1 and st.mode.value == "LIVE"
    vs = [VehicleState.model_validate(v) for v in client.get("/api/v1/vehicles").json()]
    by_tr = {v.tr_id: v for v in vs}
    assert KNOWN_TR in by_tr and UNKNOWN_UNIT in by_tr
    assert by_tr[UNKNOWN_UNIT].forecast is None and by_tr[UNKNOWN_UNIT].cur_dev_s is None
    assert abs(by_tr[KNOWN_TR].lat - 55.6655) < 1e-6          # последний валидный фикс
    tr = client.get(f"/api/v1/tracks/{KNOWN_TR}").json()
    assert len(tr["stops"]) > 0 and len(tr["trail"]) == 11
    assert _wait(lambda: hub.server.sessions == 0)


def test_garbage_connection_does_not_break_server(live):
    client, hub = live
    with socket.create_connection(("127.0.0.1", hub.server.port)) as s:
        s.sendall(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n" + bytes(range(256)))
    assert _wait(lambda: hub.server.stats.garbage_bytes > 0)
    assert client.get("/ready").status_code == 200
