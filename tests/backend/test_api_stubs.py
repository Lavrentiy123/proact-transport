"""BE-1 (A1): каркас API на заглушке — каждый ответ валиден по ``contracts.schemas``."""

import pytest
from fastapi.testclient import TestClient

from backend.app.hub import StubHub
from backend.app.main import create_app
from contracts.schemas import (ActionResponse, Alert, HorizonMetrics, SystemStatus, TrackResponse, VehicleState,
                               WsMessage)


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app(hub=StubHub(), ws_period_s=0.05)) as c:
        yield c


def test_health_ready_docs(client):
    assert client.get("/health").json() == {"status": "ok"}
    r = client.get("/ready")
    assert r.status_code == 200 and r.json()["status"] == "ready"
    assert client.get("/docs").status_code == 200
    paths = client.get("/openapi.json").json()["paths"]
    for p in ("/api/v1/system/status", "/api/v1/vehicles", "/api/v1/alerts", "/api/v1/tracks/{tr_id}",
              "/api/v1/actions", "/api/v1/metrics/horizon", "/api/v1/replay/control"):
        assert p in paths, p


def test_status(client):
    SystemStatus.model_validate(client.get("/api/v1/system/status").json())


def test_vehicles(client):
    data = client.get("/api/v1/vehicles").json()
    assert len(data) >= 1
    for v in data:
        VehicleState.model_validate(v)


def test_alerts_sorted(client):
    data = client.get("/api/v1/alerts?status=active").json()
    assert len(data) >= 1
    alerts = [Alert.model_validate(a) for a in data]
    assert [a.priority for a in alerts] == sorted((a.priority for a in alerts), reverse=True)


def test_track(client):
    tr_id = client.get("/api/v1/vehicles").json()[0]["tr_id"]
    tr = TrackResponse.model_validate(client.get(f"/api/v1/tracks/{tr_id}").json())
    assert tr.tr_id == tr_id and len(tr.stops) > 0 and len(tr.trail) >= 1
    assert client.get("/api/v1/tracks/1").status_code == 404


def test_horizon(client):
    h = HorizonMetrics.model_validate(client.get("/api/v1/metrics/horizon").json())
    assert 0.0 <= h.share_lead_in_window <= 1.0


def test_actions(client):
    alert_id = client.get("/api/v1/alerts").json()[0]["alert_id"]
    r = client.post("/api/v1/actions", json={"alert_id": alert_id, "action": "apply"})
    assert r.status_code == 200
    assert ActionResponse.model_validate(r.json()).status == "applied"
    assert client.post("/api/v1/actions", json={"alert_id": "nope", "action": "apply"}).status_code == 404
    assert client.post("/api/v1/actions", json={"alert_id": alert_id, "action": "bad"}).status_code == 422


def test_replay_control(client):
    r = client.post("/api/v1/replay/control", json={"speed": 5, "start_at": "2026-01-06T07:00:00"})
    st = SystemStatus.model_validate(r.json())
    assert st.replay_speed == 5.0


def test_ws_live(client):
    with client.websocket_connect("/ws/live") as ws:
        for _ in range(3):  # первое сообщение — сразу, дальше раз в период
            msg = WsMessage.model_validate_json(ws.receive_text())
            assert msg.type == "snapshot" and msg.vehicles and msg.status is not None
