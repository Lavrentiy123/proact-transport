"""Регрессии по независимому ревью: гонки REST, часы тика, ресинхронизация NDTP, сторожок, 409, «будущее»."""

import asyncio
import inspect
import json
import socket
import threading
import time
from datetime import datetime

import httpx
import numpy as np
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from backend.app.config import ROOT, Settings
from backend.app.emulator import EmulatorCtl
from backend.app.fleet import Fleet
from backend.app.live import LiveHub
from backend.app.main import create_app
from backend.app.ndtp.codec import NPL, DecodeStats, encode_handshake, encode_nav, iter_frames
from backend.app.predict import MlClient
from backend.app.replay import load_rows
from contracts.schemas import PredictResponse, PredictResult, Quality
from features import from_epoch_s, to_epoch_s


def test_all_rest_handlers_are_async():
    from backend.app.api import routes as api_routes
    routes = [r for r in api_routes.router.routes if isinstance(r, APIRoute)]
    assert len(routes) >= 11
    assert routes and all(inspect.iscoroutinefunction(r.endpoint) for r in routes), \
        [r.path for r in routes if not inspect.iscoroutinefunction(r.endpoint)]


def test_parallel_gets_while_new_units_arrive():
    hub = LiveHub(Settings(ndtp_port=0, ml_url=""))
    errors = []
    with TestClient(create_app(hub=hub, ws_period_s=0.05)) as c:
        now = int(hub.clock.now_s()) - 5

        def feed():
            with socket.create_connection(("127.0.0.1", hub.server.port)) as s:
                for u in range(500):
                    s.sendall(encode_nav(2_000_000 + u, u + 1, now, 55.7 + u * 1e-4, 37.6, 10, 0, True))

        def hammer():
            for _ in range(60):
                r = c.get("/api/v1/vehicles")
                if r.status_code != 200:
                    errors.append(r.status_code)

        threads = [threading.Thread(target=feed)] + [threading.Thread(target=hammer) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        deadline = time.time() + 5
        while hub.server.realtime_packets < 500 and time.time() < deadline:
            time.sleep(0.05)
        assert c.get("/api/v1/vehicles").status_code == 200
    assert errors == [] and hub.server.handler_errors == 0 and len(hub.fleet.unknown_units) == 500


def test_due_tick_rules():
    hub = LiveHub(Settings(tick_s=5.0, replay_speed=1.0))
    t = hub.ticker
    now = hub.clock.now_s()
    planned = now - 1.0                                   # момент уже наступил
    assert t.due_tick(planned, hub.clock.epoch) == planned
    assert t.due_tick(now + 10, hub.clock.epoch) is None  # часы позади плана (ушли назад)
    assert t.due_tick(now - 30, hub.clock.epoch) == (now // 5) * 5   # отстали — последняя точка сетки
    epoch = hub.clock.epoch
    hub.clock.set(start_at=now - 3600)
    assert t.due_tick(planned, epoch) is None             # перенос времени — тик пропускаем


def test_tick_loop_never_issues_future_forecast_after_clock_moved_back():
    rows = load_rows(ROOT / "data" / "test" / "traffic.csv")
    hub = LiveHub(Settings(ml_url="", replay_start_at="2026-01-06T07:05:00", replay_speed=50.0, tick_s=5.0))
    hub.fleet = Fleet.from_files(hub.s.schedule_file, hub.s.traffic_file)
    T0 = to_epoch_s("2026-01-06 07:05:00")
    for i in np.nonzero((rows.send_s >= T0 - 1800) & (rows.send_s <= T0))[0]:
        hub.fleet.on_fix(int(rows.unit[i]), float(rows.ts[i]), rows.lat[i], rows.lon[i], rows.speed[i],
                         rows.heading[i], bool(rows.valid[i]))
    hub.server.last_packet_wall = time.time()
    bad = []

    async def go():
        task = asyncio.create_task(hub.ticker._run())
        await asyncio.sleep(0.35)
        hub.clock.set(start_at=T0 - 600)                 # на 10 минут назад, пока тик спит
        hub.forecasts.clear()
        for _ in range(30):
            await asyncio.sleep(0.03)
            now = hub.clock.now()
            bad.extend(f for f in hub.forecasts.values() if f.issued_at > now.to_pydatetime())
        task.cancel()
        await hub.ticker.ml.close()

    asyncio.run(go())
    assert hub.ticker.ticks > 0 and bad == []


def test_false_header_with_plausible_size_does_not_swallow_frames():
    good = [encode_nav(7, i, 1767682800 + i, 55.7, 37.6, 20, 90, True) for i in range(5)]
    fake = b"\x7e\x7e" + (2000).to_bytes(2, "little") + b"\x00\x00" + b"\x12\x34" + b"\x02" + b"\x00" * 6
    assert len(fake) == NPL.size
    st = DecodeStats()
    frames, rest = iter_frames(fake + b"".join(good), st)
    assert len(frames) == 5 and rest == b"" and st.bad_headers >= 1


def test_corrupted_frame_covering_real_frames_keeps_them():
    real = encode_nav(9, 1, 1767682800, 55.7, 37.6, 20, 90, True)
    body = b"\x01\x00\x65\x00\x01\x00" + b"\x00" * 4 + real + real          # NPH + «тело» с настоящими кадрами
    hdr = NPL.pack(0x7E7E, len(body), 0, 0xDEAD, 0x02, 9, 0)                # CRC заведомо неверный
    st = DecodeStats()
    frames, rest = iter_frames(hdr + body, st)
    assert st.crc_errors == 1 and len(frames) == 2 and rest == b""


def test_watchdog_reposts_after_emulator_restart_for_real():
    state = {"units": [], "posts": 0}

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"units": state["units"]})
        state["posts"] += 1
        state["units"] = json.loads(request.content)["units"]
        return httpx.Response(200, json=json.loads(request.content))

    ctl = EmulatorCtl(LiveHub(Settings(emulator_api="http://emu:18080", emulator_units=2)))
    ctl.watchdog_s = 0.05

    async def go():
        ctl._client = httpx.AsyncClient(base_url="http://emu:18080", transport=httpx.MockTransport(handler))
        task = asyncio.create_task(ctl._run())
        await asyncio.sleep(0.15)
        assert state["posts"] == 1
        state["units"] = []                              # эмулятор перезапустился и потерял конфиг
        await asyncio.sleep(0.3)
        task.cancel()
        await ctl._client.aclose()

    asyncio.run(go())
    assert state["posts"] == 2 and len(state["units"]) == 2


def test_action_on_closed_alert_is_409_and_reply_flagged_emulated():
    from backend.app.alerts import recommend, risk_of
    from contracts.schemas import Cause, Forecast
    hub = LiveHub(Settings(ndtp_port=0, ml_url=""))
    with TestClient(create_app(hub=hub, ws_period_s=0.05)) as c:
        fc = Forecast(target_stop_id=1, target_stop_name="X", target_time_plan=datetime(2026, 1, 6, 7, 12),
                      issued_at=datetime(2026, 1, 6, 7, 0), lead_s=720, delay_pred_s=400, delay_q10_s=300,
                      delay_q90_s=500, p_late=0.9, risk=risk_of(400, 0.9), quality=Quality.full,
                      cause=Cause(code="congestion", text="t", evidence="e", confidence=0.5), model_version="m")
        a = hub.ticker.book.update(5, fc, recommend(fc, {"route_dist_m": 3000.0}, False), False, datetime(2026, 1, 6, 7))
        r = c.post("/api/v1/actions", json={"alert_id": a.alert_id, "action": "apply"})
        assert r.status_code == 200 and r.json()["driver_reply_emulated"] is True
        again = c.post("/api/v1/actions", json={"alert_id": a.alert_id, "action": "apply"})
        assert again.status_code == 409


def test_future_window_boundary():
    hub = LiveHub(Settings(ndtp_port=0, ml_url="", replay_speed=1.0))
    with TestClient(create_app(hub=hub, ws_period_s=0.05)):
        now = hub.clock.now_s()
        with socket.create_connection(("127.0.0.1", hub.server.port)) as s:
            s.sendall(encode_handshake(985940, 1))
            s.sendall(encode_nav(985940, 2, int(now + 20), 55.66, 37.55, 10, 0, True))   # +20 с — принят
            s.sendall(encode_nav(985940, 3, int(now + 45), 55.67, 37.56, 10, 0, True))   # +45 с — отброшен
            deadline = time.time() + 5
            while hub.server.realtime_packets < 2 and time.time() < deadline:
                time.sleep(0.05)
        assert hub.dropped_out_of_window == 1
        assert hub.fleet.vehicles[131672].last.t_s == pytest.approx(int(now + 20))


def test_missing_ml_rows_fall_back_per_bus():
    rows = load_rows(ROOT / "data" / "test" / "traffic.csv")
    hub = LiveHub(Settings(ml_url="http://ml", replay_start_at="2026-01-06T07:05:00"))
    hub.fleet = Fleet.from_files(hub.s.schedule_file, hub.s.traffic_file)
    T0 = to_epoch_s("2026-01-06 07:05:00")
    for i in np.nonzero((rows.send_s >= T0 - 1800) & (rows.send_s <= T0))[0]:
        hub.fleet.on_fix(int(rows.unit[i]), float(rows.ts[i]), rows.lat[i], rows.lon[i], rows.speed[i],
                         rows.heading[i], bool(rows.valid[i]))
    hub.server.last_packet_wall = time.time()

    def handler(request):                               # ml-core «забыл» всех бортов, кроме первого
        body = json.loads(request.content)
        first = body["rows"][0]["tr_id"]
        res = [PredictResult(tr_id=first, delta_pred_s=0, delay_pred_s=40, delay_q10_s=0, delay_q90_s=80, p_late=0.1,
                             cause_code="accumulated", cause_confidence=0.5)]
        return httpx.Response(200, text=PredictResponse(model_version="m1", latency_ms=1, results=res).model_dump_json())

    hub.ticker.ml = MlClient("http://ml", transport=httpx.MockTransport(handler))

    async def go():
        await hub.ticker.tick(T0)
        await hub.ticker.ml.close()

    asyncio.run(go())
    q = [f.quality for f in hub.forecasts.values()]
    assert len(q) >= 2 and q.count(Quality.full) + q.count(Quality.degraded) == 1 and q.count(Quality.fallback) == len(q) - 1
