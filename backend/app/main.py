"""Точка входа backend: ``uvicorn backend.app.main:app --host 0.0.0.0 --port 8000`` (из корня репозитория).

Режим данных выбирается переменной окружения ``BACKEND_STUB``:

- ``BACKEND_STUB=1`` — ЗАГЛУШКА из ``contracts/examples/ws_snapshot.json`` (для фронта без потока);
- иначе — живой режим (приём NDTP, состояние бортов, тик прогнозов).
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api import routes, ws
from .hub import Hub, StubHub

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("backend")


def _env_flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def make_hub() -> Hub:
    """Выбирает источник данных по ``BACKEND_STUB``."""
    if _env_flag("BACKEND_STUB", "1"):
        log.warning("BACKEND_STUB=1: API отдаёт заглушку из contracts/examples/ws_snapshot.json")
        return StubHub()
    raise RuntimeError("живой режим ещё не реализован: запустите с BACKEND_STUB=1")


def create_app(hub: Hub | None = None, ws_period_s: float | None = None) -> FastAPI:
    """Собирает приложение.

    Args:
        hub: источник данных (по умолчанию — :func:`make_hub`).
        ws_period_s: период рассылки WebSocket, секунды (по умолчанию 1.0 или ``WS_PERIOD_S``).
    """
    period = ws_period_s if ws_period_s is not None else float(os.getenv("WS_PERIOD_S", "1.0"))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.hub = hub if hub is not None else make_hub()
        app.state.broadcaster = ws.Broadcaster(lambda: app.state.hub.snapshot().model_dump_json(), period)
        await app.state.broadcaster.start()
        try:
            yield
        finally:
            await app.state.broadcaster.stop()

    app = FastAPI(
        title="ПроАкт.Транспорт — backend",
        description="Приём телеметрии NDTP, состояние бортов, прогноз задержки за 10–15 минут, алерты диспетчеру. "
                    "Модели ответов — contracts/schemas.py.",
        version="1.0",
        lifespan=lifespan,
    )
    app.include_router(routes.router)
    app.include_router(ws.router)
    return app


app = create_app()
