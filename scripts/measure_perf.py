"""Замеры производительности для docs/perf.md (запуск из корня репозитория, образы уже собраны).

    python scripts/measure_perf.py cold              # down → up -d → /ready, первый прогноз, первый алерт
    python scripts/measure_perf.py load --minutes 10 # при поднятом стеке: pkt/s, тик и инференс p50/p99, REST, WS
    python scripts/measure_perf.py codec             # пропускная способность парсера NDTP (без Docker)

Каждая строка вывода — JSON с одной цифрой и тем, как она получена.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")   # вывод в файл на Windows иначе cp1251
URL = "http://localhost:8000"


def get(path: str, timeout: float = 5.0):
    with urllib.request.urlopen(URL + path, timeout=timeout) as r:
        body = r.read()
    return body.decode("utf-8")


def out(**kw) -> None:
    print(json.dumps(kw, ensure_ascii=False), flush=True)


def metric(text: str, name: str) -> float | None:
    m = re.search(r"^" + re.escape(name) + r" (\S+)$", text, re.M)
    return float(m.group(1)) if m else None


def cmd_cold(timeout_s: float) -> None:
    subprocess.run(["docker", "compose", "down"], cwd=ROOT, check=True, capture_output=True)
    t0 = time.time()
    subprocess.run(["docker", "compose", "up", "-d"], cwd=ROOT, check=True, capture_output=True)
    t_up = time.time()
    out(metric="compose_up_d_s", value=round(t_up - t0, 1), how="docker compose up -d (образы собраны, контейнеры удалены)")
    marks = {}
    while time.time() - t0 < timeout_s and len(marks) < 3:
        try:
            if "ready" not in marks and urllib.request.urlopen(URL + "/ready", timeout=2).status == 200:
                marks["ready"] = time.time()
            if "ready" in marks and "forecast" not in marks and '"forecast":{' in get("/api/v1/vehicles"):
                marks["forecast"] = time.time()
            if "ready" in marks and "alert" not in marks and json.loads(get("/api/v1/alerts?status=all")):
                marks["alert"] = time.time()
        except Exception:
            pass
        time.sleep(0.5)
    for k, what in (("ready", "/ready = 200"), ("forecast", "первый борт с прогнозом"), ("alert", "первый алерт")):
        out(metric=f"cold_start_to_{k}_s", value=round(marks[k] - t0, 1) if k in marks else None,
            how=f"от `docker compose up -d` до «{what}» (replay с 07:00 ×10)")


def cmd_load(minutes: float) -> None:
    m0 = get("/metrics")
    t0 = time.time()
    rest = []
    while time.time() - t0 < minutes * 60:
        s = time.perf_counter()
        get("/api/v1/vehicles")
        rest.append((time.perf_counter() - s) * 1000)
        time.sleep(1.0)
    m1 = get("/metrics")
    dt = time.time() - t0
    pk = (metric(m1, "ndtp_packets_total") or 0) - (metric(m0, "ndtp_packets_total") or 0)
    out(metric="ndtp_packets_per_s", value=round(pk / dt, 1), how=f"разница ndtp_packets_total за {dt:.0f} с")
    for name in ('tick_duration_ms{quantile="0.5"}', 'tick_duration_ms{quantile="0.99"}',
                 'infer_ms{quantile="0.5"}', 'infer_ms{quantile="0.99"}', "tick_overruns_total", "tick_errors_total",
                 "ndtp_crc_errors_total", "tick_rows", 'dropped_total{kind="late_beyond_buffer"}',
                 'online_mae_seconds{model="forecast"}', 'online_mae_seconds{model="baseline_cur_dev"}',
                 "horizon_share_in_window", "journal_resolved_total"):
        out(metric=name, value=metric(m1, name), how="/metrics в конце прогона (квантили — последние 2000 тиков)")
    rest.sort()
    out(metric="rest_vehicles_ms_p50", value=round(rest[len(rest) // 2], 1), how=f"GET /api/v1/vehicles, {len(rest)} запросов")
    out(metric="rest_vehicles_ms_p99", value=round(rest[min(len(rest) - 1, int(len(rest) * 0.99))], 1), how="то же")

    async def ws():
        import websockets
        async with websockets.connect(URL.replace("http", "ws") + "/ws/live") as w:
            sizes = [len(await w.recv())]          # первое сообщение приходит сразу после подключения
            t = time.perf_counter()
            sizes += [len(await w.recv()) for _ in range(4)]
            return sizes, (time.perf_counter() - t) / 4
    sizes, period = asyncio.run(ws())
    out(metric="ws_snapshot_bytes", value=max(sizes), how="размер WsMessage, 5 сообщений")
    out(metric="ws_period_s", value=round(period, 2), how="средний интервал между сообщениями WS")


def cmd_codec(n: int) -> None:
    from backend.app.ndtp.codec import encode_nav, iter_frames
    blob = b"".join(encode_nav(1000 + i % 30, i, 1767682800 + i, 55.7 + i * 1e-6, 37.6, 20, 90, True) for i in range(n))
    t = time.perf_counter()
    frames, _ = iter_frames(blob)
    dt = time.perf_counter() - t
    out(metric="ndtp_parse_frames_per_s", value=round(len(frames) / dt), how=f"iter_frames на {n} кадрах Nav00, один поток")
    out(metric="ndtp_parse_us_per_frame", value=round(dt / len(frames) * 1e6, 2), how="то же")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["cold", "load", "codec"])
    p.add_argument("--minutes", type=float, default=10)
    p.add_argument("--timeout", type=float, default=300)
    p.add_argument("--frames", type=int, default=100_000)
    p.add_argument("--url", default=URL, help="адрес backend, если порт изменён в .env")
    a = p.parse_args()
    globals()["URL"] = a.url.rstrip("/")
    {"cold": lambda: cmd_cold(a.timeout), "load": lambda: cmd_load(a.minutes), "codec": lambda: cmd_codec(a.frames)}[a.mode]()


if __name__ == "__main__":
    main()
