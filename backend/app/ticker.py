"""Тик прогнозов: каждые ``tick_s`` секунд времени симуляции (по умолчанию 5 с).

Для каждого борта с расписанием:

1. целевая остановка — первая с планом в ``(T+10 мин, T+15 мин]`` (``OnlineVehicle.target_at``);
   нет такой — прогноз не строится (горизонт выдерживается по построению);
2. признаки ``OnlineVehicle.features_at(T)`` (те же, что при обучении; только ``t ≤ T``);
3. один батч ``ml-core /v1/predict`` на все борта; ``ml-core`` недоступен — fallback-правило;
   поток молчит (DEGRADED) — ``model="sched"`` (прогноз по расписанию), ``quality=fallback``;
4. риск, причина с доказательством, рекомендация, алерт с гистерезисом, запись в журнал.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import time
from collections import deque

from contracts.schemas import ActionRequest, ActionResponse, Forecast, Mode, Quality
from features import features_to_json, from_epoch_s

from .alerts import AlertBook, build_cause, recommend, risk_of
from .journal import Journal
from .predict import FALLBACK_VERSION, MlClient, rule_predict

log = logging.getLogger("backend.tick")


class Ticker:
    """Цикл тика и всё, что он обновляет (прогнозы, алерты, журнал)."""

    def __init__(self, hub):
        self.hub = hub
        s = hub.s
        self.ml = MlClient(s.ml_url, s.ml_timeout_s, s.ml_fail_threshold, s.ml_open_s)
        self.book = AlertBook()
        self.journal = Journal(s.journal_max)
        self.tick_ms: deque[float] = deque(maxlen=2000)
        self.infer_ms: deque[float] = deque(maxlen=2000)
        self.ticks = 0
        self.overruns = 0
        self.errors = 0
        self.last_tick_s: float | None = None
        self.last_source = "none"
        self.last_version = "none"
        self.last_rows = 0
        self._task: asyncio.Task | None = None

    # ---------------- жизненный цикл ----------------
    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="ticker")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await self.ml.close()

    def reset(self) -> None:
        self.book.reset()
        self.journal.reset()
        self.hub.forecasts.clear()

    def on_arrivals(self, arrivals: list[tuple[int, int, float]]) -> None:
        """Прибытия из детектора → факты для журнала прогнозов."""
        for tr, stop, t_arr in arrivals:
            self.journal.resolve(tr, stop, t_arr)

    def ml_status(self) -> tuple[bool, str, str]:
        """``(ml_core_ok, model_version, чем считается прогноз)`` для ``SystemStatus``."""
        return bool(self.ml.enabled and self.ml.last_ok), self.last_version, self.last_source

    # ---------------- цикл ----------------
    async def _run(self) -> None:
        tick = self.hub.s.tick_s
        while True:
            clock = self.hub.clock
            now = clock.now_s()
            nxt = (math.floor(now / tick) + 1) * tick
            await asyncio.sleep(max(0.0, (nxt - now) / max(clock.speed, 1e-6)))
            try:
                await self.tick(nxt)
            except Exception:
                self.errors += 1
                log.exception("tick failed")
            if self.hub.clock.now_s() > nxt + tick:
                self.overruns += 1

    async def tick(self, T: float) -> None:
        """Один тик в момент ``T`` (секунды времени симуляции)."""
        t0 = time.perf_counter()
        hub, s = self.hub, self.hub.s
        fleet = hub.fleet
        if fleet is None:
            return
        now_dt = from_epoch_s(T).to_pydatetime()
        metas = []
        for v in fleet.scheduled():
            tgt = v.online.target_at(T) if v.last_valid is not None else None
            feats = v.online.features_at(T, target=tgt) if tgt is not None else None
            if feats is None:    # борт не в эфире или нет остановки в окне 10–15 мин — прогноз не строим
                hub.forecasts.pop(v.tr_id, None)
                self.book.update(v.tr_id, None, None, False, now_dt)
                continue
            metas.append((v, tgt, feats))
        degraded = hub.mode() == Mode.degraded
        results = []
        if metas:
            rows = [{"tr_id": v.tr_id, "features": features_to_json(f)} for v, _, f in metas]
            t_inf = time.perf_counter()
            results = await self.ml.predict(rows, "sched" if degraded else "online")
            if results is not None:
                self.infer_ms.append((time.perf_counter() - t_inf) * 1000.0)
            else:
                results = [rule_predict(v.tr_id, f.get("cur_dev_s")) for v, _, f in metas]
            by_tr = {r.tr_id: r for r in results}
            for v, tgt, feats in metas:
                r = by_tr.get(v.tr_id)
                if r is not None:
                    self._apply(v, tgt, feats, r, T, now_dt, degraded)
            self.last_source = results[0].source
            self.last_version = results[0].model_version
        self.last_rows = len(metas)
        self.ticks += 1
        self.last_tick_s = T
        self.tick_ms.append((time.perf_counter() - t0) * 1000.0)

    def _apply(self, v, tgt, feats: dict, r, T: float, now_dt, degraded: bool) -> None:
        hub, s = self.hub, self.hub.s
        stop_id, plan_ts = tgt
        plan_s = plan_ts.value / 1e9
        lead_s = int(round(plan_s - T))
        if not 600 <= lead_s <= 900:      # не должно случаться: окно задаёт target_at
            log.error("lead %s outside [600, 900] for %s", lead_s, v.tr_id)
            return
        stale = (T - v.last.t_s) > s.stale_after_s if v.last is not None else True
        if r.source != "ml-core":
            quality = Quality.fallback      # ml-core недоступен или поток молчит: прогноз по расписанию/правилу
        else:
            quality = Quality.degraded if stale else Quality.full
        derived = v.online.derived(T)
        la = v.online.detector.last_arrival(T)
        last_name = v.online.stop_name(la[0]) if la is not None else None
        target_name = v.online.stop_name(stop_id)
        cause = build_cause(r.cause_code, r.cause_confidence, feats, derived, last_name, target_name, plan_s - T)
        risk = risk_of(r.delay_pred_s, r.p_late)
        fc = Forecast(target_stop_id=stop_id, target_stop_name=target_name, target_time_plan=plan_ts.to_pydatetime(),
                      issued_at=now_dt, lead_s=lead_s, delay_pred_s=round(r.delay_pred_s, 1),
                      delay_q10_s=round(r.delay_q10_s, 1), delay_q90_s=round(r.delay_q90_s, 1),
                      p_late=round(r.p_late, 3), risk=risk, quality=quality, cause=cause,
                      model_version=r.model_version)
        opening = bool(v.online.is_opening_or_closing_trip(T))
        rec = recommend(fc, feats, opening)
        self.book.update(v.tr_id, fc, rec, opening, now_dt)
        hub.forecasts[v.tr_id] = fc
        self.journal.add(T, v.tr_id, stop_id, plan_s, lead_s, r.delay_pred_s, r.delay_q10_s, r.delay_q90_s, r.p_late,
                         risk.value, quality.value, r.cause_code, feats.get("cur_dev_s"), r.model_version)

    # ---------------- решения диспетчера (шаг 10) ----------------
    def act(self, req: ActionRequest) -> ActionResponse | None:
        return None


__all__ = ["Ticker", "FALLBACK_VERSION"]
