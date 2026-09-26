"""REST-эндпоинты backend. Ответы — модели ``contracts.schemas`` (Swagger: ``/docs``)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from contracts.schemas import (ActionRequest, ActionResponse, Alert, HorizonMetrics, SystemStatus, TrackResponse,
                               VehicleState)

from ..hub import Hub, ReplayControl

router = APIRouter()


def _hub(request: Request) -> Hub:
    return request.app.state.hub


@router.get("/health", summary="Процесс жив", tags=["service"])
def health() -> dict:
    """Всегда 200, пока процесс отвечает."""
    return {"status": "ok"}


@router.get("/ready", summary="Готов принимать поток", tags=["service"])
def ready(request: Request):
    """200 — расписание загружено и NDTP-сервер слушает порт; иначе 503 с причиной."""
    ok, reason = _hub(request).ready()
    body = {"status": "ready" if ok else "not_ready", "detail": reason}
    return body if ok else JSONResponse(status_code=503, content=body)


@router.get("/api/v1/system/status", response_model=SystemStatus, tags=["system"],
            summary="Режим LIVE/DEGRADED/REPLAY, время симуляции, сессии NDTP, состояние ml-core")
def system_status(request: Request) -> SystemStatus:
    return _hub(request).status()


@router.get("/api/v1/vehicles", response_model=list[VehicleState], tags=["vehicles"],
            summary="Все борта: позиция, производные признаки, прогноз")
def vehicles(request: Request) -> list[VehicleState]:
    return _hub(request).vehicles()


@router.get("/api/v1/alerts", response_model=list[Alert], tags=["alerts"],
            summary="Алерты, сортировка по priority (больше — выше)")
def alerts(request: Request, status: str | None = "active") -> list[Alert]:
    """``status``: ``active`` (по умолчанию), ``applied``, ``dismissed``, ``resolved`` или ``all``."""
    return _hub(request).alerts(status)


@router.get("/api/v1/tracks/{tr_id}", response_model=TrackResponse, tags=["vehicles"],
            summary="Плановые остановки борта (план/факт/прогноз) и след GPS")
def track(request: Request, tr_id: int) -> TrackResponse:
    tr = _hub(request).track(tr_id)
    if tr is None:
        raise HTTPException(status_code=404, detail=f"tr_id {tr_id} не найден")
    return tr


@router.post("/api/v1/actions", response_model=ActionResponse, tags=["alerts"],
             summary="Решение диспетчера по алерту (apply/dismiss) и сообщение водителю")
def actions(request: Request, req: ActionRequest) -> ActionResponse:
    if req.action not in ("apply", "dismiss"):
        raise HTTPException(status_code=422, detail="action: apply | dismiss")
    resp = _hub(request).act(req)
    if resp is None:
        raise HTTPException(status_code=404, detail=f"alert_id {req.alert_id} не найден")
    return resp


@router.get("/api/v1/metrics/horizon", response_model=HorizonMetrics, tags=["metrics"],
            summary="Доля прогнозов с горизонтом 10–15 мин и онлайн-MAE против бейзлайна")
def horizon(request: Request) -> HorizonMetrics:
    return _hub(request).horizon()


@router.post("/api/v1/replay/control", response_model=SystemStatus, tags=["system"],
             summary="Скорость и начальный момент воспроизведения исторического дня")
def replay_control(request: Request, req: ReplayControl) -> SystemStatus:
    return _hub(request).replay_control(req)
