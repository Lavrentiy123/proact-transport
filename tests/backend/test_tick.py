"""BE-5: тик, риск, причина, рекомендация, алерты с гистерезисом, журнал, ml-core и fallback."""

import asyncio
from datetime import datetime

import httpx
import numpy as np
import pytest

from backend.app.alerts import AlertBook, build_cause, fmt_delay, recommend, risk_of
from backend.app.config import ROOT, Settings
from backend.app.journal import Journal
from backend.app.live import LiveHub
from backend.app.predict import FALLBACK_VERSION, MlClient, p_late, rule_predict
from backend.app.replay import load_rows
from contracts.schemas import Cause, Forecast, Quality, Risk, WsMessage
from features import from_epoch_s, to_epoch_s


def _fc(pred, lead=720, p=0.5, stop=1, name="Ост", risk=None):
    return Forecast(target_stop_id=stop, target_stop_name=name, target_time_plan=datetime(2026, 1, 6, 7, 12),
                    issued_at=datetime(2026, 1, 6, 7, 0), lead_s=lead, delay_pred_s=pred, delay_q10_s=pred - 100,
                    delay_q90_s=pred + 100, p_late=p, risk=risk or risk_of(pred, p), quality=Quality.full,
                    cause=Cause(code="accumulated", text="x", evidence="y", confidence=0.5), model_version="t")


def test_risk_thresholds_from_contract():
    assert risk_of(119, 0.1) == Risk.green and risk_of(120, 0.1) == Risk.yellow
    assert risk_of(299, 0.1) == Risk.yellow and risk_of(300, 0.1) == Risk.red
    assert risk_of(50, 0.8) == Risk.red


def test_fmt_and_p_late():
    assert fmt_delay(372) == "+6:12" and fmt_delay(-95) == "−1:35"
    assert p_late(120, 20, 220) == pytest.approx(0.5, abs=1e-6)
    assert p_late(500, 400, 600) > 0.99


def test_recommendations():
    feats = {"route_dist_m": 4000.0, "dist_to_target_m": 3000.0}
    r = recommend(_fc(200, lead=600), feats, False)
    assert r.action == "speed_advice" and r.target_speed_kmh == pytest.approx(24.0)
    r = recommend(_fc(-150), feats, False)
    assert r.action == "hold" and r.hold_s == 120
    assert recommend(_fc(-70), feats, False).hold_s == 70
    r = recommend(_fc(400, p=0.9), feats, True)
    assert r.action == "reserve"
    assert recommend(_fc(30), feats, False) is None


def test_cause_evidence_uses_buffer_numbers():
    c = build_cause("congestion", 0.7, {"v_mean_5m": 4.2, "stop_out_zone_s_5m": 220.0}, {}, None, "Цель", 700)
    assert c.text == "Затор на перегоне" and "4 км/ч" in c.evidence and "3:40" in c.evidence
    c = build_cause("accumulated", 0.5, {}, {"cur_dev_s": 260.0}, "Школа", "Цель", 700)
    assert "+4:20" in c.evidence and "Школа" in c.evidence


def test_alert_hysteresis_keyed_by_tr():
    book = AlertBook()
    t = datetime(2026, 1, 6, 7, 0)
    assert book.update(1, _fc(250), None, False, t) is None          # yellow — алерта нет
    a = book.update(1, _fc(350, stop=10), None, False, t)
    assert a is not None and a.status == "active"
    b = book.update(1, _fc(320, stop=11), None, False, t)              # сменилась остановка — тот же алерт
    assert b.alert_id == a.alert_id and b.forecast.target_stop_id == 11
    assert book.update(1, _fc(250), None, False, t) is a              # 250 ≥ 200 — держим
    assert book.update(1, _fc(150), None, False, t) is a              # первый спокойный тик — держим
    assert book.update(1, _fc(150), None, False, t) is None           # второй подряд — снят
    assert book.closed[-1].status == "resolved" and not book.active


def test_alert_decision_suppresses_until_calm():
    book = AlertBook()
    t = datetime(2026, 1, 6, 7, 0)
    a = book.update(2, _fc(400), None, False, t)
    assert book.decide(a.alert_id, "applied").status == "applied"
    assert book.update(2, _fc(400), None, False, t) is None           # не поднимаем снова, пока красный
    book.update(2, _fc(100), None, False, t)
    book.update(2, _fc(100), None, False, t)
    assert book.update(2, _fc(400), None, False, t) is not None       # успокоился — снова можно


def test_journal_metrics_and_csv():
    j = Journal()
    T = to_epoch_s("2026-01-06 07:00:00")
    j.add(T, 7, 100, T + 720, 720, 150.0, 50, 250, 0.6, "yellow", "full", "accumulated", 100.0, "m")
    j.add(T + 5, 7, 100, T + 720, 715, 170.0, 70, 270, 0.7, "yellow", "full", "accumulated", 100.0, "m")
    assert j.resolve(7, 100, T + 720 + 200) == 2
    m = j.metrics()
    assert m.forecasts_total == 2 and m.share_lead_in_window == 1.0 and m.resolved_total == 2
    assert m.online_mae_model_s == pytest.approx((50 + 30) / 2) and m.online_mae_baseline_s == pytest.approx(100)
    csv = j.to_csv().splitlines()
    assert csv[0].startswith("sample_id,issued_at") and csv[1].startswith(f"7_{int(T)},2026-01-06T07:00:00")


def test_rule_fallback():
    r = rule_predict(5, 100.0)
    assert r.delay_pred_s == pytest.approx(68.0) and r.source == "fallback-rule" and r.model_version == FALLBACK_VERSION
    assert r.delay_q10_s < r.delay_pred_s < r.delay_q90_s
    assert rule_predict(5, float("nan")).cause_code == "low_data"


def test_ml_client_circuit_breaker():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(500, json={"detail": "boom"})

    ml = MlClient("http://ml", fail_threshold=3, open_s=30, transport=httpx.MockTransport(handler))

    async def go():
        out = [await ml.predict([{"tr_id": 1, "features": {}}]) for _ in range(5)]
        await ml.close()
        return out

    out = asyncio.run(go())
    assert out == [None] * 5 and calls["n"] == 3 and ml.state == "open"   # после 3 ошибок в ml-core не ходим


def _feed(hub, rows, t_until):
    m = rows.send_s <= t_until
    for i in np.nonzero(m)[0]:
        hub.fleet.on_fix(int(rows.unit[i]), float(rows.ts[i]), rows.lat[i], rows.lon[i], rows.speed[i],
                         rows.heading[i], bool(rows.valid[i]))


@pytest.fixture(scope="module")
def rows():
    return load_rows(ROOT / "data" / "test" / "traffic.csv")


def _run_ticks(hub, rows, start, n_ticks):
    """Подаёт телеметрию до каждого T и делает тик (без реального времени)."""
    from backend.app.fleet import Fleet
    hub.fleet = Fleet.from_files(hub.s.schedule_file, hub.s.traffic_file)
    hub.server.last_packet_wall = __import__("time").time()          # поток «идёт» — режим LIVE
    T0 = to_epoch_s(start)
    m0 = (rows.send_s >= T0 - 1800) & (rows.send_s <= T0)
    for i in np.nonzero(m0)[0]:
        hub.fleet.on_fix(int(rows.unit[i]), float(rows.ts[i]), rows.lat[i], rows.lon[i], rows.speed[i],
                         rows.heading[i], bool(rows.valid[i]))
    cursor = int(np.searchsorted(rows.send_s, T0, side="right"))

    async def go():
        nonlocal cursor
        for k in range(n_ticks):
            T = T0 + 5 * k
            while cursor < len(rows.send_s) and rows.send_s[cursor] <= T:
                arr = hub.fleet.on_fix(int(rows.unit[cursor]), float(rows.ts[cursor]), rows.lat[cursor],
                                       rows.lon[cursor], rows.speed[cursor], rows.heading[cursor],
                                       bool(rows.valid[cursor]))
                if arr:
                    hub.ticker.on_arrivals(arr)
                cursor += 1
            await hub.ticker.tick(T)
        await hub.ticker.ml.close()

    asyncio.run(go())


def test_tick_fallback_without_ml_core(rows):
    hub = LiveHub(Settings(ml_url="", replay_start_at="2026-01-06T07:00:00"))
    _run_ticks(hub, rows, "2026-01-06T07:00:00", 24)     # 2 минуты симуляции
    assert hub.forecasts, "нет прогнозов"
    for fc in hub.forecasts.values():
        assert 600 <= fc.lead_s <= 900 and fc.quality == Quality.fallback and fc.model_version == FALLBACK_VERSION
        assert fc.target_time_plan > fc.issued_at
    m = hub.horizon()
    assert m.forecasts_total > 0 and m.share_lead_in_window == 1.0
    assert hub.status().ml_core_ok is False


@pytest.fixture(scope="module")
def ml_transport():
    pytest.importorskip("catboost")
    from ml_core.app.main import app, predictor
    predictor.load()
    assert predictor.ready, predictor.error
    return httpx.ASGITransport(app=app)


def test_tick_with_ml_core_real_day_raises_red_alert(rows, ml_transport):
    """Настоящий ml-core (m_online) на реальном дне: прогнозы full, горизонт 1.0, красный алерт поднимается.

    На test-дне первый красный прогноз модели — в 07:27 (07:00–07:10 красных нет), поэтому окно 07:00–07:35.
    """
    hub = LiveHub(Settings(ml_url="http://ml-core", replay_start_at="2026-01-06T07:00:00"))
    hub.ticker.ml = MlClient("http://ml-core", timeout_s=5, transport=ml_transport)
    _run_ticks(hub, rows, "2026-01-06T07:00:00", 420)    # 07:00–07:35, тик 5 с
    fcs = list(hub.forecasts.values())
    assert fcs and all(fc.quality in (Quality.full, Quality.degraded) for fc in fcs)
    assert all(fc.model_version.startswith("m_online") for fc in fcs)
    m = hub.horizon()
    assert m.share_lead_in_window == 1.0 and m.forecasts_total >= 1000 and m.resolved_total > 0
    assert hub.ticker.book.raised_total >= 1, "за 07:00–07:35 не поднялся ни один алерт"
    alerts = sorted(list(hub.ticker.book.active.values()) + list(hub.ticker.book.closed), key=lambda a: a.created_at)
    first = alerts[0]
    assert first.created_at >= datetime(2026, 1, 6, 7, 10)            # фиксируем наблюдение: не раньше 07:10
    assert first.risk == Risk.red and first.forecast.cause.evidence and first.title.startswith("Борт ")
    WsMessage.model_validate_json(hub.snapshot().model_dump_json())
