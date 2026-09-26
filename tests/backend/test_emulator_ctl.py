"""BE-9: управление официальным эмулятором — формат конфига и сторожок после перезапуска."""

import asyncio
import json

import httpx

from backend.app.config import Settings
from backend.app.emulator import ONE_SHOT_INTERVAL_MS, EmulatorCtl, nav_fields
from backend.app.live import LiveHub
from features import to_epoch_s


def test_nav_fields_format_verified_on_emulator():
    f = nav_fields(55.8040083, 37.43070705, 23.4, 90.2, True)
    assert f == {"longitude": 374307070, "latitude": 558040083, "extraDopBit5": True, "extraDopBit6": True,
                 "extraDopBit7": True, "speedAvg": 23, "course": 90}
    bad = nav_fields(float("nan"), float("nan"), float("nan"), float("nan"), True)
    assert bad["extraDopBit7"] is False and bad["latitude"] == 0 and bad["speedAvg"] == 0


def test_auto_and_trajectory_configs():
    hub = LiveHub(Settings(emulator_api="http://emu:18080", emulator_units=5, emulator_interval_ms=1000))
    ctl = EmulatorCtl(hub)
    cfg = ctl.auto_config()
    assert cfg["targetHost"] == "backend" and cfg["targetPort"] == 9201 and len(cfg["units"]) == 5
    assert all(u["autoGenerate"] and u["intervalMs"] == 1000 for u in cfg["units"])
    tj = ctl.trajectory_config(to_epoch_s("2026-01-06 07:10:00"))
    assert 5 <= len(tj["units"]) <= 30
    u = tj["units"][0]
    assert u["autoGenerate"] is False and u["intervalMs"] == ONE_SHOT_INTERVAL_MS
    assert u["cells"][0]["type"] == "G6CellNav00" and "latitude" in u["cells"][0]["fields"]   # формат «fields»
    json.dumps(tj)                       # значения из numpy сериализуются (ошибка, пойманная на живом эмуляторе)


def test_watchdog_reposts_after_emulator_restart():
    state = {"units": [], "posts": 0}

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"targetHost": None, "targetPort": None, "units": state["units"]})
        state["posts"] += 1
        state["units"] = json.loads(request.content)["units"]
        return httpx.Response(200, json=json.loads(request.content))

    hub = LiveHub(Settings(emulator_api="http://emu:18080", emulator_units=2))
    ctl = EmulatorCtl(hub)

    async def go():
        ctl._client = httpx.AsyncClient(base_url="http://emu:18080", transport=httpx.MockTransport(handler))
        task = asyncio.create_task(ctl._run())
        await asyncio.sleep(0.2)
        assert state["posts"] == 1 and ctl.state.startswith("configured")
        task.cancel()
        await ctl._client.aclose()

    asyncio.run(go())
    assert len(state["units"]) == 2


def test_first_contact_replaces_foreign_config():
    state = {"units": [{"unitId": 1}] * 5, "posts": 0}

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"units": state["units"]})
        state["posts"] += 1
        state["units"] = json.loads(request.content)["units"]
        return httpx.Response(200, json=json.loads(request.content))

    hub = LiveHub(Settings(emulator_api="http://emu:18080", emulator_units=2))
    ctl = EmulatorCtl(hub)

    async def go():
        ctl._client = httpx.AsyncClient(base_url="http://emu:18080", transport=httpx.MockTransport(handler))
        task = asyncio.create_task(ctl._run())
        await asyncio.sleep(0.2)
        task.cancel()
        await ctl._client.aclose()

    asyncio.run(go())
    assert state["posts"] == 1 and len(state["units"]) == 2
