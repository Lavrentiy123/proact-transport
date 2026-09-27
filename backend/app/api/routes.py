"""REST-эндпоинты backend. Ответы — модели ``contracts.schemas`` (Swagger: ``/docs``).

Все обработчики — ``async def``: FastAPI выполняет синхронные обработчики в пуле потоков, а состояние
бортов, алертов и журнала меняется в event loop (приём NDTP, тик). В одном потоке гонок нет.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from contracts.schemas import (ActionRequest, ActionResponse, Alert, HorizonMetrics, SystemStatus, TrackResponse,
                               VehicleState)

from ..hub import ActionResponseEx, AlertNotActive, Hub, ReplayControl, SystemStatusEx

router = APIRouter()


def _hub(request: Request) -> Hub:
    return request.app.state.hub


@router.get("/health", summary="Процесс жив", tags=["service"])
async def health() -> dict:
    """Всегда 200, пока процесс отвечает."""
    return {"status": "ok"}


@router.get("/ready", summary="Готов принимать поток", tags=["service"])
async def ready(request: Request):
    """200 — расписание загружено и NDTP-сервер слушает порт; иначе 503 с причиной."""
    ok, reason = _hub(request).ready()
    body = {"status": "ready" if ok else "not_ready", "detail": reason}
    return body if ok else JSONResponse(status_code=503, content=body)


@router.get("/api/v1/system/status", response_model=SystemStatusEx, tags=["system"],
            summary="Режим LIVE/DEGRADED, время симуляции, сессии NDTP, состояние ml-core")
async def system_status(request: Request) -> SystemStatus:
    """``SystemStatus`` контракта плюс необязательные счётчики приёма NDTP."""
    return _hub(request).status()


@router.get("/api/v1/vehicles", response_model=list[VehicleState], tags=["vehicles"],
            summary="Все борта: позиция, производные признаки, прогноз")
async def vehicles(request: Request) -> list[VehicleState]:
    return _hub(request).vehicles()


@router.get("/api/v1/alerts", response_model=list[Alert], tags=["alerts"],
            summary="Алерты, сортировка по priority (больше — выше)")
async def alerts(request: Request, status: str | None = "active") -> list[Alert]:
    """``status``: ``active`` (по умолчанию), ``applied``, ``dismissed``, ``resolved`` или ``all``."""
    return _hub(request).alerts(status)


@router.get("/api/v1/tracks/{tr_id}", response_model=TrackResponse, tags=["vehicles"],
            summary="Плановые остановки борта (план/факт/прогноз) и след GPS")
async def track(request: Request, tr_id: int) -> TrackResponse:
    tr = _hub(request).track(tr_id)
    if tr is None:
        raise HTTPException(status_code=404, detail=f"tr_id {tr_id} не найден")
    return tr


@router.post("/api/v1/actions", response_model=ActionResponseEx, tags=["alerts"],
             summary="Решение диспетчера по алерту (apply/dismiss) и сообщение водителю")
async def actions(request: Request, req: ActionRequest) -> ActionResponse:
    if req.action not in ("apply", "dismiss"):
        raise HTTPException(status_code=422, detail="action: apply | dismiss")
    try:
        resp = _hub(request).act(req)
    except AlertNotActive as e:
        raise HTTPException(status_code=409, detail=str(e))
    if resp is None:
        raise HTTPException(status_code=404, detail=f"alert_id {req.alert_id} не найден")
    return resp


@router.get("/api/v1/metrics/horizon", response_model=HorizonMetrics, tags=["metrics"],
            summary="Доля прогнозов с горизонтом 10–15 мин и онлайн-MAE против бейзлайна")
async def horizon(request: Request) -> HorizonMetrics:
    return _hub(request).horizon()


@router.post("/api/v1/replay/control", response_model=SystemStatusEx, tags=["system"],
             summary="Скорость и начальный момент воспроизведения исторического дня")
async def replay_control(request: Request, req: ReplayControl) -> SystemStatus:
    return _hub(request).replay_control(req)


@router.get("/api/v1/journal.csv", response_class=PlainTextResponse, tags=["metrics"],
            summary="Журнал прогнозов потока (CSV): горизонт, прогноз, факт из детектора прибытий")
async def journal_csv(request: Request):
    """Колонка ``sample_id`` = ``{tr_id}_{T}`` — как в ``validate/points.csv`` (сабмит из потока)."""
    from starlette.concurrency import run_in_threadpool
    snap = _hub(request).journal_snapshot()          # копия строк — в event loop
    body = await run_in_threadpool(snap) if snap is not None else None   # форматирование CSV — вне loop
    if body is None:
        raise HTTPException(status_code=404, detail="журнал есть только в живом режиме")
    return PlainTextResponse(body, media_type="text/csv; charset=utf-8")


@router.get("/metrics", response_class=PlainTextResponse, tags=["metrics"],
            summary="Метрики Prometheus: пакеты NDTP, CRC, тик и инференс p50/p99, WS, отброшенное")
async def metrics(request: Request):
    from ..metrics import render
    return PlainTextResponse(render(_hub(request), getattr(request.app.state, "broadcaster", None)),
                             media_type="text/plain; version=0.0.4; charset=utf-8")
