"""Интерфейс источника данных для API и реализация-заглушка.

Роуты REST и WebSocket не знают, откуда берутся данные: они вызывают методы :class:`Hub`.
:class:`StubHub` отдаёт пример из ``contracts/examples/ws_snapshot.json`` (для разработки фронта
без потока), живая реализация — :class:`backend.app.live.LiveHub`.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from contracts.schemas import (ActionRequest, ActionResponse, Alert, HorizonMetrics, StopOnTrack, SystemStatus,
                               TrackResponse, VehicleState, WsMessage)

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_SNAPSHOT = ROOT / "contracts" / "examples" / "ws_snapshot.json"


class SystemStatusEx(SystemStatus):
    """``SystemStatus`` из контракта + необязательные счётчики приёма NDTP (контракт не меняется:
    новые необязательные поля разрешены правилом ``contracts/README.md``, модель объявлена в backend)."""

    ndtp_connections_total: int | None = None
    ndtp_packets_total: int | None = Field(None, description="realtime-пакетов принято")
    ndtp_nav_fixes_total: int | None = None
    ndtp_crc_errors_total: int | None = None
    ndtp_garbage_bytes_total: int | None = None
    unknown_units: int | None = Field(None, description="терминалов без расписания (только на карте)")
    ndtp_dropped_out_of_window: int | None = Field(None, description="пакетов вне окна «сейчас − 40 мин … + 60 с»")
    predictor: str | None = Field(None, description="чем считается прогноз: ml-core | fallback-rule | none")


class ReplayControl(BaseModel):
    """Тело ``POST /api/v1/replay/control`` (пример из ``contracts/README.md``)."""

    speed: float | None = Field(None, gt=0, le=60, examples=[5])
    start_at: datetime | None = Field(None, examples=["2026-01-06T07:00:00"])


class Hub:
    """Что backend умеет отдавать наружу. Все методы возвращают модели ``contracts.schemas``."""

    is_stub = False

    async def start(self) -> None:
        """Запуск фоновых компонентов (TCP-сервер, тик); у заглушки — ничего."""

    async def stop(self) -> None:
        """Остановка фоновых компонентов."""

    def ready(self) -> tuple[bool, str]:
        """``(готов, причина)`` для ``/ready``."""
        raise NotImplementedError

    def status(self) -> SystemStatus:
        raise NotImplementedError

    def vehicles(self) -> list[VehicleState]:
        raise NotImplementedError

    def alerts(self, status: str | None = "active") -> list[Alert]:
        raise NotImplementedError

    def track(self, tr_id: int) -> TrackResponse | None:
        raise NotImplementedError

    def horizon(self) -> HorizonMetrics:
        raise NotImplementedError

    def act(self, req: ActionRequest) -> ActionResponse | None:
        raise NotImplementedError

    def replay_control(self, req: ReplayControl) -> SystemStatus:
        raise NotImplementedError

    def snapshot(self) -> WsMessage:
        raise NotImplementedError

    def journal_csv(self) -> str | None:
        """Журнал прогнозов в CSV (``None`` — журнала нет)."""
        return None


class StubHub(Hub):
    """ЗАГЛУШКА: данные из ``contracts/examples/ws_snapshot.json``, без потока и без модели.

    Нужна только для разработки фронта (``BACKEND_STUB=1``). Плановые остановки в ``/tracks``
    берутся из планового расписания ``data/test/schedule.csv`` (без фактов), остальное — из примера.
    """

    is_stub = True

    def __init__(self, example_path: Path = EXAMPLE_SNAPSHOT, schedule_path: Path | None = None):
        raw = json.loads(Path(example_path).read_text(encoding="utf-8"))
        self._msg = WsMessage.model_validate(raw)
        self._alerts = {a.alert_id: a for a in (self._msg.alerts or [])}
        self._schedule_path = schedule_path or ROOT / "data" / "test" / "schedule.csv"
        self._schedule = None

    def ready(self) -> tuple[bool, str]:
        return True, "stub: contracts/examples/ws_snapshot.json"

    def status(self) -> SystemStatus:
        return self._msg.status.model_copy()

    def vehicles(self) -> list[VehicleState]:
        return [v.model_copy() for v in self._msg.vehicles or []]

    def alerts(self, status: str | None = "active") -> list[Alert]:
        out = [a for a in self._alerts.values() if status in (None, "", "all") or a.status == status]
        return sorted(out, key=lambda a: a.priority, reverse=True)

    def _stops(self, tr_id: int) -> list[StopOnTrack]:
        if self._schedule is None:
            from features import load_schedule
            self._schedule = load_schedule(self._schedule_path)
        rows = self._schedule[self._schedule.tr_id == tr_id]
        return [StopOnTrack(stop_id=int(r.stop_id), name=r.name, lat=float(r.lat), lon=float(r.lon), seq=i,
                            time_plan=r.time_plan.to_pydatetime())
                for i, r in enumerate(rows.itertuples(index=False))]

    def track(self, tr_id: int) -> TrackResponse | None:
        veh = next((v for v in self._msg.vehicles or [] if v.tr_id == tr_id), None)
        if veh is None:
            return None
        return TrackResponse(tr_id=tr_id, stops=self._stops(tr_id), trail=[(self._msg.sim_time, veh.lat, veh.lon)])

    def horizon(self) -> HorizonMetrics:
        fc = [v.forecast for v in self._msg.vehicles or [] if v.forecast is not None]
        in_win = sum(1 for f in fc if 600 <= f.lead_s <= 900)
        return HorizonMetrics(forecasts_total=len(fc), share_lead_in_window=(in_win / len(fc)) if fc else 0.0,
                              resolved_total=0, online_mae_model_s=None, online_mae_baseline_s=None)

    def act(self, req: ActionRequest) -> ActionResponse | None:
        alert = self._alerts.get(req.alert_id)
        if alert is None:
            return None
        alert.status = "applied" if req.action == "apply" else "dismissed"
        text = alert.recommendation.text if alert.recommendation else alert.title
        return ActionResponse(alert_id=req.alert_id, status=alert.status, driver_message=text, driver_reply=None)

    def replay_control(self, req: ReplayControl) -> SystemStatus:
        st = self._msg.status
        if req.speed is not None:
            st.replay_speed = float(req.speed)
        if req.start_at is not None:
            st.sim_time = req.start_at
        return st.model_copy()

    def snapshot(self) -> WsMessage:
        return copy.deepcopy(self._msg)
