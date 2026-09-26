"""Живой источник данных API: поток NDTP → реестр бортов → (тик прогнозов) → REST и WebSocket."""

from __future__ import annotations

import logging
import math
import time

from contracts.schemas import (ActionRequest, ActionResponse, Alert, HorizonMetrics, Mode, StopOnTrack, SystemStatus,
                               TrackResponse, VehicleState, WsMessage)
from features import from_epoch_s

from .clock import SimClock
from .config import Settings
from .fleet import Fleet, Tracked
from .hub import Hub, ReplayControl, SystemStatusEx
from .ndtp.codec import Frame
from .ndtp.server import NdtpServer

log = logging.getLogger("backend.live")


def _num(x, default=None):
    """NaN/inf → ``default`` (в JSON NaN недопустим)."""
    if x is None:
        return default
    x = float(x)
    return x if math.isfinite(x) else default


class LiveHub(Hub):
    """Живой режим: приём NDTP, состояние бортов, прогнозы и алерты.

    Args:
        settings: настройки (по умолчанию — из окружения).
        fleet: реестр бортов (по умолчанию — из файлов настроек).
    """

    def __init__(self, settings: Settings | None = None, fleet: Fleet | None = None):
        self.s = settings or Settings.from_env()
        self.clock = SimClock(self.s.replay_start_at, self.s.replay_speed)
        self.fleet = fleet
        self.server = NdtpServer(self.on_frame, self.s.ndtp_host, self.s.ndtp_port, self.s.ndtp_idle_timeout_s)
        self.started_wall = time.time()
        self.forecasts: dict = {}          # tr_id -> Forecast (заполняет тик)
        from .ticker import Ticker
        self.ticker = Ticker(self)
        self.dropped_out_of_window = 0
        self.replay = None                 # replay внутри процесса (REPLAY_INPROCESS=1)
        self._replay_task = None

    # ---------------- жизненный цикл ----------------
    async def start(self) -> None:
        if self.fleet is None:
            t0 = time.perf_counter()
            self.fleet = Fleet.from_files(self.s.schedule_file, self.s.traffic_file)
            log.info("fleet loaded: %d scheduled buses, %d unit ids in %.2f s", len(self.fleet.sched_by_tr),
                     len(self.fleet.unit_map), time.perf_counter() - t0)
        await self.server.start()
        if self.ticker is not None:
            await self.ticker.start()
        if self.s.replay_inprocess:
            import asyncio

            from .replay import ReplayClient, load_rows
            self.replay = ReplayClient(load_rows(self.s.traffic_file), "127.0.0.1", self.server.port, self.clock,
                                       preroll_s=self.s.replay_preroll_min * 60)
            self._replay_task = asyncio.create_task(self.replay.run(), name="replay")

    async def stop(self) -> None:
        if self.replay is not None:
            self.replay.stop()
            if self._replay_task is not None:
                await self._replay_task
        if self.ticker is not None:
            await self.ticker.stop()
        await self.server.stop()

    def ready(self) -> tuple[bool, str]:
        if self.fleet is None:
            return False, "schedule not loaded"
        if not self.server.listening:
            return False, "NDTP server not listening"
        return True, f"schedule: {len(self.fleet.sched_by_tr)} buses; NDTP :{self.server.port}"

    # ---------------- приём пакетов ----------------
    def on_frame(self, fr: Frame) -> None:
        """Кадр NDTP → пакеты в реестр бортов (время — по часам симуляции)."""
        if not fr.is_realtime or self.fleet is None:
            return
        now = self.clock.now_s()
        for nav in fr.navs:
            t_s = self.clock.to_sim(nav.ts)
            if t_s < now - self.s.accept_past_s or t_s > now + self.s.accept_future_s:
                self.dropped_out_of_window += 1   # пакет вне окна «сейчас − 40 мин … сейчас + 60 с»
                continue
            arrivals = self.fleet.on_fix(fr.unit_id, t_s, nav.lat, nav.lon, nav.speed, nav.course, nav.valid)
            if arrivals and self.ticker is not None:
                self.ticker.on_arrivals(arrivals)

    # ---------------- режим ----------------
    def last_packet_age_s(self) -> float:
        lp = self.server.last_packet_wall
        return (time.time() - lp) if lp is not None else (time.time() - self.started_wall)

    def mode(self) -> Mode:
        """LIVE — пакеты NDTP идут; DEGRADED — пакетов нет дольше ``degraded_after_s`` (реальное время)."""
        if self.server.last_packet_wall is None or self.last_packet_age_s() >= self.s.degraded_after_s:
            return Mode.degraded
        return Mode.live

    # ---------------- ответы API ----------------
    def status(self) -> SystemStatus:
        st = self.server.stats
        ml_ok, version, predictor = (self.ticker.ml_status() if self.ticker is not None
                                     else (False, "none", "none"))
        return SystemStatusEx(
            mode=self.mode(), sim_time=self.clock.now().to_pydatetime(), replay_speed=self.clock.speed,
            ndtp_sessions=self.server.sessions, last_packet_age_s=round(self.last_packet_age_s(), 2),
            ml_core_ok=ml_ok, model_version=version,
            ndtp_connections_total=self.server.connections_total, ndtp_packets_total=self.server.realtime_packets,
            ndtp_nav_fixes_total=self.server.nav_fixes, ndtp_crc_errors_total=st.crc_errors,
            ndtp_garbage_bytes_total=st.garbage_bytes,
            unknown_units=len(self.fleet.unknown_units) if self.fleet else 0, predictor=predictor,
            ndtp_dropped_out_of_window=self.dropped_out_of_window)

    def _vehicle_state(self, v: Tracked, now_s: float) -> VehicleState | None:
        if v.last_valid is None or v.last is None:
            return None     # ни одного достоверного фикса — на карту не поставить
        fx = v.last_valid
        last_seen = max(0.0, now_s - v.last.t_s)
        d = v.online.derived(now_s) if v.online is not None else {}
        return VehicleState(
            tr_id=v.tr_id, lat=fx.lat, lon=fx.lon, speed_kmh=_num(fx.speed, 0.0), heading=_num(fx.heading, 0.0),
            cur_dev_s=_num(d.get("cur_dev_s")), seg_speed_kmh=_num(d.get("seg_speed_kmh")),
            dwell_s=_num(d.get("dwell_s")), last_seen_s=round(last_seen, 1), stale=last_seen > self.s.stale_after_s,
            is_opening_or_closing_trip=bool(v.online.is_opening_or_closing_trip(now_s)) if v.online else False,
            forecast=self.forecasts.get(v.tr_id))

    def vehicles(self) -> list[VehicleState]:
        if self.fleet is None:
            return []
        now_s = self.clock.now_s()
        out = [self._vehicle_state(v, now_s) for v in self.fleet.vehicles.values()]
        return [v for v in out if v is not None]

    def alerts(self, status: str | None = "active") -> list[Alert]:
        pool = list(self.ticker.book.active.values()) + list(self.ticker.book.closed)
        out = [a for a in pool if status in (None, "", "all") or a.status == status]
        return sorted(out, key=lambda a: a.priority, reverse=True)

    def track(self, tr_id: int) -> TrackResponse | None:
        if self.fleet is None or tr_id not in self.fleet.vehicles:
            return None
        v = self.fleet.vehicles[tr_id]
        fact = dict(v.arrivals)          # stop_id -> t_arr_s (детектор, не факты расписания)
        fc = self.forecasts.get(tr_id)
        stops = []
        rows = self.fleet.sched_by_tr.get(tr_id)
        if rows is not None:
            for i, r in enumerate(rows.itertuples(index=False)):
                sid = int(r.stop_id)
                t_fc = None
                if fc is not None and fc.target_stop_id == sid:
                    t_fc = from_epoch_s(r.time_plan.value / 1e9 + fc.delay_pred_s).to_pydatetime()
                stops.append(StopOnTrack(stop_id=sid, name=r.name, lat=float(r.lat), lon=float(r.lon), seq=i,
                                         time_plan=r.time_plan.to_pydatetime(),
                                         time_fact=from_epoch_s(fact[sid]).to_pydatetime() if sid in fact else None,
                                         time_forecast=t_fc))
        trail = [(from_epoch_s(t).to_pydatetime(), lat, lon) for t, lat, lon in v.trail]
        return TrackResponse(tr_id=tr_id, stops=stops, trail=trail)

    def horizon(self) -> HorizonMetrics:
        if self.ticker is not None:
            return self.ticker.journal.metrics()
        return HorizonMetrics(forecasts_total=0, share_lead_in_window=0.0, resolved_total=0,
                              online_mae_model_s=None, online_mae_baseline_s=None)

    def act(self, req: ActionRequest) -> ActionResponse | None:
        if self.ticker is not None:
            return self.ticker.act(req)
        return None

    def replay_control(self, req: ReplayControl) -> SystemStatus:
        moved = self.clock.set(req.start_at, req.speed)
        if moved:
            self.reset_state()
        log.info("replay control: start_at=%s speed=%s (reset=%s)", req.start_at, self.clock.speed, moved)
        return self.status()

    def reset_state(self) -> None:
        """Перенос времени симуляции: буферы, детекторы, прогнозы, алерты и журнал — заново."""
        if self.fleet is not None:
            self.fleet.reset()
        self.forecasts.clear()
        self.ticker.reset()

    def journal_csv(self) -> str | None:
        return self.ticker.journal.to_csv()

    def snapshot(self) -> WsMessage:
        return WsMessage(type="snapshot", sim_time=self.clock.now().to_pydatetime(), vehicles=self.vehicles(),
                         alerts=self.alerts("active"), status=self.status())
