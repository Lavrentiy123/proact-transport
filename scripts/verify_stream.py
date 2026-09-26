"""Воспроизводимые проверки потока для отчёта (стек `docker compose` поднят; запуск из корня репозитория).

    python scripts/verify_stream.py vehicles [--gap 5]      # два среза /api/v1/vehicles: сколько бортов, сколько сдвинулось,
                                                           # сколько терминалов с координатами в потоке по данным (receive_time)
    python scripts/verify_stream.py first-alert [--limit 300]  # секунды от вызова до первого алерта (запускать сразу после up/перезапуска)
    python scripts/verify_stream.py ws                       # одно сообщение /ws/live проходит WsMessage.model_validate_json
    python scripts/verify_stream.py degraded [--source replay] # точка отсчёта DEGRADED: от команды stop, от конца stop, от последнего пакета

Все выводы — строки «ключ: значение», их можно вставлять в отчёт как есть.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")


def get(url: str, path: str):
    with urllib.request.urlopen(url + path, timeout=5) as r:
        return json.loads(r.read())


def cmd_vehicles(url: str, gap: float) -> None:
    import numpy as np

    from backend.app.replay import load_rows
    from features import to_epoch_s
    v1 = {v["tr_id"]: v for v in get(url, "/api/v1/vehicles")}
    s1 = get(url, "/api/v1/system/status")
    time.sleep(gap)
    v2 = {v["tr_id"]: v for v in get(url, "/api/v1/vehicles")}
    s2 = get(url, "/api/v1/system/status")
    moved = sum(1 for k in v2 if k in v1 and (v1[k]["lat"], v1[k]["lon"]) != (v2[k]["lat"], v2[k]["lon"]))
    print(f"t1: sim={s1['sim_time']} sessions={s1['ndtp_sessions']} vehicles={len(v1)}")
    print(f"t2: sim={s2['sim_time']} sessions={s2['ndtp_sessions']} vehicles={len(v2)} moved={moved} mode={s2['mode']}")
    r = load_rows(ROOT / "data" / "test" / "traffic.csv")
    now = to_epoch_s(s2["sim_time"])
    m = (r.send_s <= now) & (r.send_s >= now - 1800) & (r.ts >= now - 2400)
    valid = m & r.valid & np.isfinite(r.lat)
    print(f"data (receive_time within last 30 min of sim): units_sending={len(np.unique(r.unit[m]))} "
          f"units_with_valid_fix={len(np.unique(r.unit[valid]))} units_in_csv={len(np.unique(r.unit))}")


def cmd_first_alert(url: str, limit: float) -> None:
    t0 = time.time()
    while time.time() - t0 < limit:
        try:
            al = get(url, "/api/v1/alerts?status=all")
        except Exception:
            al = []
        if al:
            a = sorted(al, key=lambda x: x["created_at"])[0]
            st = get(url, "/api/v1/system/status")
            print(f"first_alert_after_s: {time.time() - t0:.1f}")
            print(f"alert: {a['alert_id']} created_at(sim)={a['created_at']} quality={a['forecast']['quality']} "
                  f"model={a['forecast']['model_version']} sim_now={st['sim_time']}")
            return
        time.sleep(1)
    print(f"first_alert_after_s: none within {limit:.0f} s")


def cmd_ws(url: str) -> None:
    import websockets

    from contracts.schemas import WsMessage

    async def go():
        async with websockets.connect(url.replace("http", "ws") + "/ws/live") as w:
            return WsMessage.model_validate_json(await w.recv())
    m = asyncio.run(go())
    fc = [v for v in m.vehicles or [] if v.forecast]
    print(f"ws: valid WsMessage type={m.type} sim_time={m.sim_time} vehicles={len(m.vehicles or [])} "
          f"with_forecast={len(fc)} alerts={len(m.alerts or [])} mode={m.status.mode.value}")


def cmd_degraded(url: str, source: str) -> None:
    t_cmd = time.time()
    subprocess.run(["docker", "compose", "stop", source], cwd=ROOT, check=True, capture_output=True)
    t_done = time.time()
    age_at_stop = get(url, "/api/v1/system/status")["last_packet_age_s"]
    while True:
        st = get(url, "/api/v1/system/status")
        if st["mode"] == "DEGRADED":
            t_deg = time.time()
            break
        time.sleep(0.1)
    print(f"stop_command_duration_s: {t_done - t_cmd:.1f}")
    print(f"degraded_after_stop_command_start_s: {t_deg - t_cmd:.1f}")
    print(f"degraded_after_stop_command_end_s: {t_deg - t_done:.1f}")
    print(f"degraded_after_last_packet_s: {t_deg - t_done + age_at_stop:.1f} (last_packet_age at stop end {age_at_stop:.2f} s)")
    health = urllib.request.urlopen(url + "/health", timeout=5).status
    print(f"health_during_degraded: {health}")
    t_start = time.time()
    subprocess.run(["docker", "compose", "start", source], cwd=ROOT, check=True, capture_output=True)
    while get(url, "/api/v1/system/status")["mode"] != "LIVE":
        time.sleep(0.1)
    print(f"live_after_start_command_s: {time.time() - t_start:.1f}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("check", choices=["vehicles", "first-alert", "ws", "degraded"])
    p.add_argument("--url", default="http://localhost:8000")
    p.add_argument("--gap", type=float, default=5.0)
    p.add_argument("--limit", type=float, default=300.0)
    p.add_argument("--source", default="replay")
    a = p.parse_args()
    {"vehicles": lambda: cmd_vehicles(a.url, a.gap), "first-alert": lambda: cmd_first_alert(a.url, a.limit),
     "ws": lambda: cmd_ws(a.url), "degraded": lambda: cmd_degraded(a.url, a.source)}[a.check]()


if __name__ == "__main__":
    main()
