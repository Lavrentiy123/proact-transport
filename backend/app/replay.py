"""Replay реального дня: ``data/test/traffic.csv`` → бинарные кадры NDTP → TCP :9201.

Каждый терминал (``unit_id``) — своё TCP-соединение: handshake, затем ``G6CellNav00`` на каждую
строку телеметрии. Метка ``timestamp`` = время датасета как наивное UTC (как ``features.to_epoch_s``).
Пакеты уходят в момент ``receive_time`` (когда их получил сервер организаторов; буферизованные
``is_hist_data`` поэтому приходят с опозданием, как в жизни), но не раньше ``event_time``.
Невалидные фиксы тоже отправляются (бит валидности = 0).

Часы симуляции:

- ``--sync-url http://backend:8000`` — время и скорость берутся у backend (``/api/v1/system/status``),
  перезапуск replay продолжает с текущего момента backend (так проверяется обрыв потока);
- без ``--sync-url`` — собственные часы с ``--start-at`` и ``--speed``.

Перед стартом (и после переноса времени) отправляется «разгон» — последние ``--preroll-min`` минут
телеметрии пачкой, чтобы у бортов заполнились буфер и детектор прибытий.

Запуск: ``python -m backend.app.replay --host 127.0.0.1 --port 9201 --sync-url http://127.0.0.1:8000``.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import math
import signal
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from features import to_epoch_s

from .clock import SimClock
from .config import ROOT
from .ndtp.codec import encode_handshake, encode_nav

log = logging.getLogger("backend.replay")
JUMP_S = 60.0          # расхождение часов больше этого — перемотка
SYNC_EVERY_S = 2.0     # как часто сверять часы с backend (реальные секунды)


@dataclass
class Rows:
    """Телеметрия в порядке отправки (numpy-массивы)."""

    send_s: np.ndarray
    ts: np.ndarray
    unit: np.ndarray
    lat: np.ndarray
    lon: np.ndarray
    speed: np.ndarray
    heading: np.ndarray
    valid: np.ndarray


def load_rows(traffic_file: Path) -> Rows:
    """Читает ``traffic.csv`` и сортирует по моменту отправки ``max(event_time, receive_time)``."""
    df = pd.read_csv(traffic_file, usecols=["unit_id", "event_time", "receive_time", "location_valid", "lat", "lon",
                                            "speed", "heading"], low_memory=False)
    et = pd.to_datetime(df.event_time, format="ISO8601")
    rt = pd.to_datetime(df.receive_time, format="ISO8601", errors="coerce").fillna(et)
    ts = et.to_numpy("datetime64[ns]").astype(np.int64) / 1e9
    send = np.maximum(ts, rt.to_numpy("datetime64[ns]").astype(np.int64) / 1e9)
    valid = df.location_valid.astype(str).str.strip().str.lower().isin({"true", "1"}).to_numpy()
    order = np.argsort(send, kind="stable")

    def col(c, fill=np.nan):
        return pd.to_numeric(df[c], errors="coerce").fillna(fill).to_numpy(np.float64)[order]

    return Rows(send_s=send[order], ts=ts[order], unit=df.unit_id.to_numpy(np.int64)[order],
                lat=col("lat"), lon=col("lon"), speed=col("speed", 0.0), heading=col("heading", 0.0),
                valid=valid[order])


class HttpClock:
    """Часы, сверяемые с backend: ``sim_time`` и ``replay_speed`` из ``/api/v1/system/status``."""

    def __init__(self, url: str):
        self.url = url.rstrip("/") + "/api/v1/system/status"
        self.anchor_sim = math.nan
        self.anchor_wall = 0.0
        self.speed = 1.0

    def sync(self) -> bool:
        try:
            with urllib.request.urlopen(self.url, timeout=2) as r:
                st = json.loads(r.read())
        except Exception as e:
            log.warning("clock sync failed: %s", e)
            return False
        self.anchor_sim = to_epoch_s(st["sim_time"])
        self.anchor_wall = time.time()
        self.speed = float(st["replay_speed"])
        return True

    def now_s(self) -> float:
        return self.anchor_sim + (time.time() - self.anchor_wall) * self.speed


class ReplayClient:
    """Отправляет телеметрию датасета по NDTP, соблюдая часы симуляции.

    Args:
        rows: телеметрия (:func:`load_rows`).
        host, port: NDTP-сервер.
        clock: :class:`backend.app.clock.SimClock` или :class:`HttpClock`.
        preroll_s: длина «разгона», секунды симуляции.
        loop: по концу дня начать сначала.
        tick_wall_s: период цикла отправки, реальные секунды.
    """

    def __init__(self, rows: Rows, host: str, port: int, clock, preroll_s: float = 1800.0, loop: bool = False,
                 tick_wall_s: float = 0.05):
        self.rows, self.host, self.port, self.clock = rows, host, port, clock
        self.preroll_s, self.loop, self.tick_wall_s = preroll_s, loop, tick_wall_s
        self.writers: dict[int, asyncio.StreamWriter] = {}
        self.rid: dict[int, int] = {}
        self.retry_at: dict[int, float] = {}
        self.sent = 0
        self.dropped = 0
        self.reconnects = 0
        self.cursor = 0
        self.ended = False
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    async def _connect(self, unit: int) -> asyncio.StreamWriter | None:
        now = time.time()
        if self.retry_at.get(unit, 0.0) > now:
            return None
        try:
            _r, w = await asyncio.wait_for(asyncio.open_connection(self.host, self.port), timeout=3)
        except (OSError, asyncio.TimeoutError) as e:
            self.retry_at[unit] = now + 2.0
            log.debug("connect unit %s failed: %s", unit, e)
            return None
        self.rid[unit] = 1
        w.write(encode_handshake(int(unit), 1))
        self.writers[unit] = w
        if unit in self.retry_at:
            self.reconnects += 1
            self.retry_at.pop(unit, None)
        return w

    async def _send(self, i: int) -> None:
        r = self.rows
        unit = int(r.unit[i])
        w = self.writers.get(unit) or await self._connect(unit)
        if w is None:
            self.dropped += 1
            return
        self.rid[unit] = self.rid.get(unit, 1) + 1
        frame = encode_nav(unit, self.rid[unit], int(round(r.ts[i])), r.lat[i], r.lon[i], r.speed[i], r.heading[i],
                           bool(r.valid[i]))
        try:
            w.write(frame)
            self.sent += 1
        except (ConnectionError, RuntimeError, OSError):
            self._drop_writer(unit)
            self.dropped += 1

    def _drop_writer(self, unit: int) -> None:
        w = self.writers.pop(unit, None)
        if w is not None:
            w.close()
        self.retry_at[unit] = time.time() + 1.0

    def seek(self, sim_s: float) -> int:
        """Курсор на начало «разгона» перед ``sim_s``; возвращает число строк разгона."""
        start = int(np.searchsorted(self.rows.send_s, sim_s - self.preroll_s, side="left"))
        end = int(np.searchsorted(self.rows.send_s, sim_s, side="right"))
        self.cursor = start
        return end - start

    async def _flush(self) -> None:
        for unit, w in list(self.writers.items()):
            try:
                await asyncio.wait_for(w.drain(), timeout=2)
            except (ConnectionError, OSError, asyncio.TimeoutError, RuntimeError):
                self._drop_writer(unit)

    async def run(self, duration_wall_s: float | None = None) -> None:
        """Основной цикл; ``duration_wall_s`` — остановиться через столько реальных секунд (для тестов)."""
        is_http = isinstance(self.clock, HttpClock)
        while is_http and not self.clock.sync() and not self._stop.is_set():
            await asyncio.sleep(1.0)
        t_end = time.time() + duration_wall_s if duration_wall_s else math.inf
        n_pre = self.seek(self.clock.now_s())
        log.info("replay start at sim %s, preroll %d rows, speed x%s", pd.Timestamp(self.clock.now_s() * 1e9),
                 n_pre, self.clock.speed)
        last_sync = time.time()
        expected = self.clock.now_s()
        try:
            while not self._stop.is_set() and time.time() < t_end:
                if is_http and time.time() - last_sync >= SYNC_EVERY_S:
                    before = self.clock.now_s()
                    if self.clock.sync() and abs(self.clock.now_s() - before) > JUMP_S:
                        log.info("clock jump %.0f s -> reseek", self.clock.now_s() - before)
                        self.seek(self.clock.now_s())
                    last_sync = time.time()
                now = self.clock.now_s()
                if abs(now - expected) > JUMP_S:   # часы перенесены (SimClock.set) — перемотка с разгоном
                    log.info("clock jump %.0f s -> reseek", now - expected)
                    self.seek(now)
                expected = now
                r = self.rows
                n = len(r.send_s)
                while self.cursor < n and r.send_s[self.cursor] <= now:
                    await self._send(self.cursor)
                    self.cursor += 1
                    if self.cursor % 500 == 0:
                        await self._flush()
                await self._flush()
                if self.cursor >= n:
                    if self.loop:
                        self.cursor = 0
                    elif not self.ended:
                        # конец дня: не выходим (иначе restart-политика compose гоняла бы контейнер по кругу),
                        # ждём остановки или переноса часов назад (перемотка выше)
                        log.info("replay reached end of data, idle")
                        self.ended = True
                elif self.ended:
                    self.ended = False
                await asyncio.sleep(self.tick_wall_s)
        finally:
            for u in list(self.writers):
                self._drop_writer(u)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Replay исторического дня по NDTP")
    p.add_argument("--traffic", default=str(ROOT / "data" / "test" / "traffic.csv"))
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9201)
    p.add_argument("--sync-url", default="", help="URL backend: брать время симуляции у него")
    p.add_argument("--start-at", default="2026-01-06T07:00:00")
    p.add_argument("--speed", type=float, default=10.0)
    p.add_argument("--preroll-min", type=float, default=30.0)
    p.add_argument("--loop", action="store_true")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    rows = load_rows(Path(a.traffic))
    clock = HttpClock(a.sync_url) if a.sync_url else SimClock(a.start_at, a.speed)
    client = ReplayClient(rows, a.host, a.port, clock, preroll_s=a.preroll_min * 60, loop=a.loop)

    async def run_until_signal() -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            with contextlib.suppress(NotImplementedError, RuntimeError):   # Windows: без обработчиков сигналов
                loop.add_signal_handler(sig, client.stop)
        await client.run()
        log.info("replay stopped: sent=%d dropped=%d reconnects=%d", client.sent, client.dropped, client.reconnects)

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run_until_signal())


if __name__ == "__main__":
    main()
