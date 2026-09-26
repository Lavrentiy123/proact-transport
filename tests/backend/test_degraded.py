"""BE-7: режим DEGRADED при обрыве потока, stale-борта, восстановление, прогноз по расписанию."""

import asyncio
import json
import time

import httpx
import numpy as np
import pytest

from backend.app.config import ROOT, Settings
from backend.app.fleet import Fleet
from backend.app.live import LiveHub
from backend.app.predict import MlClient
from backend.app.replay import load_rows
from contracts.schemas import Mode, PredictResponse, PredictResult, Quality
from features import to_epoch_s


@pytest.fixture(scope="module")
def rows():
    return load_rows(ROOT / "data" / "test" / "traffic.csv")


def _hub_with_state(rows, T0):
    hub = LiveHub(Settings(ml_url="http://ml", replay_start_at="2026-01-06T07:00:00"))
    hub.fleet = Fleet.from_files(hub.s.schedule_file, hub.s.traffic_file)
    m = (rows.send_s >= T0 - 1800) & (rows.send_s <= T0)
    for i in np.nonzero(m)[0]:
        hub.fleet.on_fix(int(rows.unit[i]), float(rows.ts[i]), rows.lat[i], rows.lon[i], rows.speed[i],
                         rows.heading[i], bool(rows.valid[i]))
    return hub


def _fake_ml(seen):
    def handler(request):
        body = json.loads(request.content)
        seen.append(body["model"])
        res = [PredictResult(tr_id=r["tr_id"], delta_pred_s=0, delay_pred_s=50, delay_q10_s=0, delay_q90_s=100,
                             p_late=0.1, cause_code="accumulated", cause_confidence=0.5) for r in body["rows"]]
        return httpx.Response(200, text=PredictResponse(model_version="fake-v1", latency_ms=1.0,
                                                        results=res).model_dump_json())
    return httpx.MockTransport(handler)


def test_mode_transitions_live_degraded_live():
    hub = LiveHub(Settings(degraded_after_s=15))
    assert hub.mode() == Mode.degraded                       # ни одного пакета — DEGRADED
    hub.server.last_packet_wall = time.time() - 1
    assert hub.mode() == Mode.live
    hub.server.last_packet_wall = time.time() - 15.5
    assert hub.mode() == Mode.degraded                       # нет пакетов ≥ 15 с
    hub.server.last_packet_wall = time.time()
    assert hub.mode() == Mode.live                           # пакет пришёл — сразу LIVE


def test_tick_in_degraded_uses_sched_and_marks_fallback(rows):
    T0 = to_epoch_s("2026-01-06 07:05:00")
    hub = _hub_with_state(rows, T0)
    seen = []
    hub.ticker.ml = MlClient("http://ml", transport=_fake_ml(seen))
    hub.server.last_packet_wall = time.time() - 60            # поток молчит минуту

    async def go():
        await hub.ticker.tick(T0 + 20)
        await hub.ticker.ml.close()

    asyncio.run(go())
    assert seen == ["sched"]
    assert hub.forecasts and all(f.quality == Quality.fallback for f in hub.forecasts.values())
    st = hub.status()
    assert st.mode == Mode.degraded and st.predictor == "ml-core:sched"


def test_stale_vehicle_marked_and_degraded_quality(rows):
    T0 = to_epoch_s("2026-01-06 07:05:00")
    hub = _hub_with_state(rows, T0)
    seen = []
    hub.ticker.ml = MlClient("http://ml", transport=_fake_ml(seen))
    hub.server.last_packet_wall = time.time()                 # поток идёт, но борта молчат 60 с симуляции
    hub.clock.set(start_at=T0 + 60)

    async def go():
        await hub.ticker.tick(T0 + 60)
        await hub.ticker.ml.close()

    asyncio.run(go())
    assert seen == ["online"]
    fcs = list(hub.forecasts.values())
    assert fcs and all(f.quality == Quality.degraded for f in fcs)   # ml-core работает, данные старше 30 с
    vs = hub.vehicles()
    assert vs and all(v.stale for v in vs if v.last_seen_s > 30)
    assert any(v.stale for v in vs)
