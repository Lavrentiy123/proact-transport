"""Управление официальным эмулятором NDTP (``ndtp-telemetry-emulator:1.0``) по его REST на :18080.

Эмулятор — TCP-клиент: после ``POST /api/config`` он сам подключается к ``targetHost:targetPort``
(наш backend :9201) и шлёт пакеты. Проверено на образе: каждый ``POST`` рвёт все сессии и открывает
их заново; явные координаты принимаются только в формате ``{"type": "G6CellNav00", "fields": {...}}``;
``timestamp`` в пакете всегда текущее время (backend переводит его в время симуляции по часам).

Режимы (``EMULATOR_MODE``):

- ``auto`` — ``EMULATOR_UNITS`` юнитов ``autoGenerate`` с ``unitId`` вне датасета (совместимость и нагрузка;
  прогнозов по ним нет — у них нет расписания);
- ``trajectories`` — реальные треки ``data/test/traffic.csv``: раз в ``TRAJECTORY_STEP_S`` секунд симуляции
  новый ``POST`` с последним фиксом каждого терминала (первый пакет эмулятор шлёт сразу после ``POST``).
  Рассчитан на скорость ×1…×5: каждый ``POST`` переподключает все юниты.

Сторожок: раз в 10 с ``GET /api/config``; если конфиг пуст (эмулятор перезапустился) — ``POST`` заново.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math

import httpx
import numpy as np

log = logging.getLogger("backend.emulator")
WATCHDOG_S = 10.0
ONE_SHOT_INTERVAL_MS = 3_600_000     # в режиме trajectories: только первый (немедленный) пакет после POST


def nav_fields(lat: float, lon: float, speed: float, course: float, valid: bool) -> dict:
    """Поля ячейки ``G6CellNav00`` для конфига эмулятора (координаты × 1e7, знаки — биты 5/6)."""
    lat, lon, speed, course = float(lat), float(lon), float(speed), float(course)   # numpy → Python (JSON)
    ok = bool(valid) and math.isfinite(lat) and math.isfinite(lon)
    lat_v, lon_v = (lat, lon) if ok else (0.0, 0.0)
    return {"longitude": int(round(abs(lon_v) * 1e7)), "latitude": int(round(abs(lat_v) * 1e7)),
            "extraDopBit5": bool(lat_v >= 0), "extraDopBit6": bool(lon_v >= 0), "extraDopBit7": ok,
            "speedAvg": int(max(0, min(65535, round(speed if math.isfinite(speed) else 0)))),
            "course": int(max(0, min(360, round(course if math.isfinite(course) else 0))))}


class EmulatorCtl:
    """Настраивает эмулятор и следит, чтобы конфиг не потерялся.

    Args:
        hub: ``LiveHub`` (часы, порт NDTP, настройки).
    """

    def __init__(self, hub):
        self.hub = hub
        s = hub.s
        self.api = s.emulator_api.rstrip("/")
        self.mode = s.emulator_mode
        self.state = "disabled" if not self.api else "starting"
        self.posts = 0
        self.errors = 0
        self.watchdog_s = WATCHDOG_S
        self._rows = None
        self._task: asyncio.Task | None = None
        self._client: httpx.AsyncClient | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.api)

    def base_config(self) -> dict:
        s = self.hub.s
        return {"targetHost": s.emulator_target_host, "targetPort": s.ndtp_port}

    def auto_config(self) -> dict:
        s = self.hub.s
        units = [{"unitId": s.emulator_unit_base + i, "intervalMs": s.emulator_interval_ms, "autoGenerate": True,
                  "cells": []} for i in range(s.emulator_units)]
        return {**self.base_config(), "units": units}

    def trajectory_config(self, sim_s: float) -> dict:
        """Последний фикс каждого терминала к моменту ``sim_s`` (по моменту получения, как replay)."""
        if self._rows is None:
            from .replay import load_rows
            self._rows = load_rows(self.hub.s.traffic_file)
        r = self._rows
        hi = int(np.searchsorted(r.send_s, sim_s, side="right"))
        lo = int(np.searchsorted(r.send_s, sim_s - self.hub.s.trajectory_step_s * 3, side="left"))
        last: dict[int, int] = {}
        for i in range(lo, hi):
            last[int(r.unit[i])] = i
        units = [{"unitId": u, "intervalMs": ONE_SHOT_INTERVAL_MS, "autoGenerate": False,
                  "cells": [{"type": "G6CellNav00",
                             "fields": nav_fields(r.lat[i], r.lon[i], r.speed[i], r.heading[i], bool(r.valid[i]))}]}
                 for u, i in sorted(last.items())]
        return {**self.base_config(), "units": units}

    async def start(self) -> None:
        if self.enabled:
            if self.mode == "trajectories" and self._rows is None:   # чтение CSV — вне event loop
                from .replay import load_rows
                self._rows = await asyncio.to_thread(load_rows, self.hub.s.traffic_file)
            self._client = httpx.AsyncClient(base_url=self.api, timeout=5.0)
            self._task = asyncio.create_task(self._run(), name="emulator-ctl")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        if self._client is not None:
            await self._client.aclose()

    async def post(self, cfg: dict) -> bool:
        try:
            r = await self._client.post("/api/config", json=cfg)
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        except Exception as e:
            self.errors += 1
            if self.state != "unreachable":
                log.warning("emulator %s: %s", self.api, e)
            self.state = "unreachable"
            return False
        self.posts += 1
        self.state = f"configured:{self.mode}:{len(cfg['units'])} units"
        return True

    async def _configured_units(self) -> int | None:
        try:
            r = await self._client.get("/api/config")
            return len(r.json().get("units") or [])
        except Exception:
            return None

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        last_check = 0.0
        while True:
            if self.mode == "trajectories":
                await self.post(self.trajectory_config(self.hub.clock.now_s()))
                wall = self.hub.s.trajectory_step_s / max(self.hub.clock.speed, 1e-6)
                await asyncio.sleep(max(1.0, wall))
                continue
            now = loop.time()
            if now - last_check >= self.watchdog_s or self.state in ("starting", "unreachable"):
                n = await self._configured_units()
                if n is None:
                    if self.state != "unreachable":
                        log.warning("emulator %s unreachable", self.api)
                    self.state = "unreachable"
                elif n == 0 or not self.state.startswith("configured"):
                    # первый контакт — всегда свой конфиг (у эмулятора мог остаться чужой);
                    # пустой конфиг — эмулятор перезапустился и всё забыл
                    log.info("emulator config: %d units -> POST %d units (mode %s)", n, self.hub.s.emulator_units,
                             self.mode)
                    await self.post(self.auto_config())
                last_check = now
            await asyncio.sleep(min(2.0, self.watchdog_s) if self.state == "unreachable" else self.watchdog_s)
