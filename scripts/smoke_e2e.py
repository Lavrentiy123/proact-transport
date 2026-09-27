"""Сквозной smoke всей системы после `docker compose up`: backend, ml-core, frontend, WebSocket.

Проверки:
- ``GET :8000/health`` == 200; ``GET :8001/ready`` == 200; ``GET :3000`` отдаёт HTML;
- ``GET :8000/api/v1/vehicles`` — непустой список ``VehicleState``;
- те же ``/api/v1/vehicles`` и ``/ws/live`` отвечают через nginx дашборда (как у браузера);
- из ``/ws/live`` приходит ``WsMessage`` с ``type=snapshot`` и хотя бы одним бортом, у которого
  ``forecast.lead_s ∈ [600, 900]`` (ждём до 60 с — replay должен дойти до прогнозов).

Запуск: ``.venv312/Scripts/python.exe scripts/smoke_e2e.py [--backend http://localhost:8000] ...``; exit 0/1.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contracts.schemas import VehicleState, WsMessage  # noqa: E402


def check_http(args) -> list[str]:
    errs = []
    with httpx.Client(timeout=10) as c:
        for name, url, ok in [
            ("backend /health", f"{args.backend}/health", lambda r: r.status_code == 200),
            ("ml-core /ready", f"{args.ml_core}/ready", lambda r: r.status_code == 200),
            ("frontend /", f"{args.frontend}/", lambda r: r.status_code == 200 and "<html" in r.text.lower()),
        ]:
            try:
                r = c.get(url)
                print(f"{'OK ' if ok(r) else 'BAD'} {name}: {r.status_code}")
                if not ok(r):
                    errs.append(f"{name}: HTTP {r.status_code}")
            except Exception as e:
                print(f"BAD {name}: {e}")
                errs.append(f"{name}: {e}")
        deadline = time.time() + args.timeout
        while True:
            try:
                r = c.get(f"{args.backend}/api/v1/vehicles")
                vs = [VehicleState.model_validate(v) for v in r.json()] if r.status_code == 200 else []
                if vs:
                    print(f"OK  /api/v1/vehicles: {len(vs)} бортов")
                    break
            except Exception:
                pass
            if time.time() > deadline:
                errs.append("/api/v1/vehicles: пустой список или ошибка")
                print("BAD /api/v1/vehicles")
                break
            time.sleep(2)
    return errs


def check_via_frontend(args) -> list[str]:
    """REST через прокси nginx дашборда: браузер ходит на тот же хост, что и страница."""
    try:
        r = httpx.get(f"{args.frontend}/api/v1/vehicles", timeout=10)
        vs = [VehicleState.model_validate(v) for v in r.json()] if r.status_code == 200 else []
        if vs:
            print(f"OK  дашборд → /api/v1/vehicles (nginx): {len(vs)} бортов")
            return []
        return [f"дашборд → /api/v1/vehicles: HTTP {r.status_code}, бортов {len(vs)}"]
    except Exception as e:
        return [f"дашборд → /api/v1/vehicles: {type(e).__name__}: {e}"]


async def check_ws(args, base: str | None = None, name: str = "/ws/live") -> list[str]:
    import websockets

    url = (base or args.backend).replace("http", "ws", 1) + "/ws/live"
    deadline = time.time() + args.timeout
    n_msg = 0
    try:
        async with websockets.connect(url, open_timeout=10) as ws:
            while time.time() < deadline:
                raw = await asyncio.wait_for(ws.recv(), timeout=max(1.0, deadline - time.time()))
                msg = WsMessage.model_validate(json.loads(raw))
                n_msg += 1
                if msg.type != "snapshot" or not msg.vehicles:
                    continue
                good = [v for v in msg.vehicles if v.forecast is not None and 600 <= v.forecast.lead_s <= 900]
                if good:
                    f = good[0].forecast
                    print(f"OK  {name}: {n_msg} сообщений, бортов {len(msg.vehicles)}, с прогнозом {len(good)}; "
                          f"пример: борт {good[0].tr_id} lead {f.lead_s} с, delay {f.delay_pred_s:.0f} с, "
                          f"risk {f.risk}, cause {f.cause.code}")
                    return []
    except Exception as e:
        return [f"{name}: {type(e).__name__}: {e}"]
    return [f"{name}: за {args.timeout} с нет snapshot с forecast.lead_s в [600, 900] ({n_msg} сообщений)"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="http://localhost:8000")
    ap.add_argument("--ml-core", default="http://localhost:8001")
    ap.add_argument("--frontend", default="http://localhost:3000")
    ap.add_argument("--timeout", type=float, default=60.0)
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):   # консоль Windows в cp1251 не печатает «→»
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    errs = check_http(args)
    errs += asyncio.run(check_ws(args))
    # то же через nginx дашборда — так, как ходит браузер (прокси /api и /ws на backend)
    errs += check_via_frontend(args)
    errs += asyncio.run(check_ws(args, args.frontend, "дашборд → /ws/live (nginx)"))
    print("E2E SMOKE " + ("OK" if not errs else "FAIL:\n  - " + "\n  - ".join(errs)))
    return 0 if not errs else 1


if __name__ == "__main__":
    sys.exit(main())
