"""BE-10: POST /api/v1/actions — решение диспетчера и эмуляция ответа водителя."""

from datetime import datetime

from fastapi.testclient import TestClient

from backend.app.alerts import recommend, risk_of
from backend.app.config import Settings
from backend.app.live import LiveHub
from backend.app.main import create_app
from contracts.schemas import ActionResponse, Alert, Cause, Forecast, Quality

REPLIES = {"успеваю", "не успеваю", "нештатная ситуация"}


def _forecast(pred, p, code="congestion", stop=53700172828):
    return Forecast(target_stop_id=stop, target_stop_name="Ул. Гарибальди", target_time_plan=datetime(2026, 1, 6, 7, 12),
                    issued_at=datetime(2026, 1, 6, 7, 0), lead_s=720, delay_pred_s=pred, delay_q10_s=pred - 80,
                    delay_q90_s=pred + 80, p_late=p, risk=risk_of(pred, p), quality=Quality.full,
                    cause=Cause(code=code, text="Затор на перегоне", evidence="4 км/ч за 5 мин", confidence=0.6),
                    model_version="m_online-test")


def test_actions_apply_dismiss_and_404():
    hub = LiveHub(Settings(ndtp_port=0, ml_url=""))
    with TestClient(create_app(hub=hub, ws_period_s=0.05)) as c:
        now = datetime(2026, 1, 6, 7, 0)
        fc1 = _forecast(360, 0.9)
        a1 = hub.ticker.book.update(131672, fc1, recommend(fc1, {"route_dist_m": 4000.0}, False), False, now)
        fc2 = _forecast(420, 0.95, code="low_data", stop=1)
        a2 = hub.ticker.book.update(122658, fc2, None, False, now)
        assert {a["alert_id"] for a in c.get("/api/v1/alerts").json()} == {a1.alert_id, a2.alert_id}

        r = c.post("/api/v1/actions", json={"alert_id": a1.alert_id, "action": "apply", "comment": "проверка"})
        assert r.status_code == 200
        resp = ActionResponse.model_validate(r.json())
        assert resp.status == "applied" and resp.driver_message.startswith("Диспетчер: Держать среднюю скорость")
        assert resp.driver_reply == "успеваю"            # нужно 20 км/ч ≤ 35 — водитель успевает (эмуляция)

        r2 = ActionResponse.model_validate(c.post("/api/v1/actions", json={"alert_id": a2.alert_id,
                                                                            "action": "apply"}).json())
        assert r2.driver_reply == "нештатная ситуация"   # low_data — связи с бортом нет

        active = [Alert.model_validate(a) for a in c.get("/api/v1/alerts").json()]
        assert active == []
        applied = c.get("/api/v1/alerts?status=applied").json()
        assert {a["alert_id"] for a in applied} == {a1.alert_id, a2.alert_id}
        assert c.post("/api/v1/actions", json={"alert_id": "нет-такого", "action": "apply"}).status_code == 404
        assert len(hub.ticker.audit) == 2 and hub.ticker.audit[0]["comment"] == "проверка"

        fc3 = _forecast(500, 0.99, stop=7)
        a3 = hub.ticker.book.update(130072, fc3, None, False, now)
        d = ActionResponse.model_validate(c.post("/api/v1/actions", json={"alert_id": a3.alert_id,
                                                                           "action": "dismiss"}).json())
        assert d.status == "dismissed" and d.driver_reply is None
        assert all(x in REPLIES for x in (resp.driver_reply, r2.driver_reply))
