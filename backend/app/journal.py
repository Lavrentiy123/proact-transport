"""Журнал прогнозов — доказательство для критерия 2 (горизонт 10–15 мин на потоке).

Каждый прогноз тика пишется строкой ``issued_at, tr_id, stop_id, time_plan, lead_s, delay_pred_s,
cur_dev_s``. Когда детектор прибытий (``features.StopDetector``) фиксирует прибытие борта на эту
остановку, строке дописывается факт ``t_arr − time_plan``. Факты расписания (``time_fact_begin``)
не используются: «факт» здесь — то, что увидел поток.

``sample_id`` = ``{tr_id}_{T}`` (T — секунды времени датасета), как в ``validate/points.csv``:
по выгрузке ``/api/v1/journal.csv`` можно собрать сабмит из потока.
"""

from __future__ import annotations

import csv
import io
import math
from collections import defaultdict

from contracts.schemas import HorizonMetrics
from features import from_epoch_s

COLUMNS = ["sample_id", "issued_at", "tr_id", "stop_id", "time_plan", "lead_s", "delay_pred_s", "delay_q10_s",
           "delay_q90_s", "p_late", "risk", "quality", "cause_code", "cur_dev_s", "model_version", "fact_delay_s"]


class Journal:
    """Журнал прогнозов с инкрементальными метриками.

    Args:
        max_rows: сколько строк хранить (старые вытесняются, метрики считаются по всем записанным).
    """

    def __init__(self, max_rows: int = 300_000):
        self.max_rows = max_rows
        self.reset()

    def reset(self) -> None:
        self.rows: list[list] = []
        self.offset = 0                      # сколько строк вытеснено
        self._open: dict[tuple[int, int], list[int]] = defaultdict(list)   # (tr, stop) -> глобальные индексы
        self.total = 0
        self.in_window = 0
        self.resolved = 0
        self.sum_err = 0.0
        self.sum_base = 0.0
        self.n_base = 0

    def add(self, issued_s: float, tr_id: int, stop_id: int, plan_s: float, lead_s: int, pred: float, q10: float,
            q90: float, p_late: float, risk: str, quality: str, cause: str, cur_dev_s: float | None,
            model_version: str) -> None:
        """Записывает прогноз."""
        idx = self.offset + len(self.rows)
        self.rows.append([f"{tr_id}_{int(round(issued_s))}", issued_s, tr_id, stop_id, plan_s, lead_s, pred, q10, q90,
                          p_late, risk, quality, cause,
                          cur_dev_s if cur_dev_s is not None and math.isfinite(cur_dev_s) else None,
                          model_version, None])
        self._open[(tr_id, stop_id)].append(idx)
        self.total += 1
        if 600 <= lead_s <= 900:
            self.in_window += 1
        if len(self.rows) > self.max_rows:
            drop = len(self.rows) - self.max_rows
            del self.rows[:drop]
            self.offset += drop

    def resolve(self, tr_id: int, stop_id: int, t_arr_s: float) -> int:
        """Прибытие борта на остановку → факт для всех прогнозов на неё. Возвращает число сверенных."""
        idxs = self._open.pop((tr_id, stop_id), None)
        if not idxs:
            return 0
        n = 0
        for g in idxs:
            i = g - self.offset
            if i < 0:
                continue
            row = self.rows[i]
            fact = t_arr_s - row[4]
            row[15] = fact
            self.resolved += 1
            self.sum_err += abs(row[6] - fact)
            if row[13] is not None:
                self.sum_base += abs(row[13] - fact)
                self.n_base += 1
            n += 1
        return n

    def metrics(self) -> HorizonMetrics:
        return HorizonMetrics(
            forecasts_total=self.total,
            share_lead_in_window=(self.in_window / self.total) if self.total else 0.0,
            resolved_total=self.resolved,
            online_mae_model_s=(self.sum_err / self.resolved) if self.resolved else None,
            online_mae_baseline_s=(self.sum_base / self.n_base) if self.n_base else None)

    def to_csv(self) -> str:
        """Весь хранимый журнал в CSV (время — ISO, время датасета)."""
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(COLUMNS)
        for r in self.rows:
            out = list(r)
            out[1] = from_epoch_s(r[1]).isoformat()
            out[4] = from_epoch_s(r[4]).isoformat()
            w.writerow(["" if v is None else (round(v, 2) if isinstance(v, float) else v) for v in out])
        return buf.getvalue()
