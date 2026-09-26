"""Прогноз для тика: клиент ``ml-core`` с circuit breaker и встроенное fallback-правило.

- Основной путь — один батч ``POST {ML_URL}/v1/predict`` на все борта тика (таймаут ``ml_timeout_s``).
- ``ml_fail_threshold`` ошибок подряд → breaker открыт на ``ml_open_s`` секунд, затем одна пробная
  попытка (half-open).
- Пока ``ml-core`` недоступен — правило ``0.6·cur_dev + 8`` (``cur_dev`` восстановлен детектором
  прибытий, NaN → 0) с ``quality=fallback``. Это аварийный режим: на размеченном test это правило
  даёт MAE 136.1 с (нулевой прогноз — 103.3 с, m_online по LOBO — 83.0 с), см. отчёт.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass

import httpx

from contracts.schemas import PredictRequest, PredictResponse

log = logging.getLogger("backend.predict")

FALLBACK_VERSION = "fallback-rule-0.6cur+8"
RULE_A, RULE_B = 0.6, 8.0
RULE_MAE_TEST_S = 136.1            # MAE правила на labels_test с восстановленным cur_dev (отчёт, шаг 5)
LAPLACE_Q90 = math.log(5.0)        # квантиль 0.9 распределения Лапласа в единицах MAE
LATE_S = 120.0
Z_10_90 = 2.563
SIGMA_MIN_S = 20.0


def p_late(pred: float, q10: float, q90: float, threshold_s: float = LATE_S) -> float:
    """P(задержка > threshold) в нормальном приближении по квантилям q10–q90."""
    sigma = max((q90 - q10) / Z_10_90, SIGMA_MIN_S)
    z = (threshold_s - pred) / sigma
    return float(min(1.0, max(0.0, 0.5 * math.erfc(z / math.sqrt(2.0)))))


@dataclass
class Result:
    """Прогноз одного борта (поля ``PredictResult`` + откуда он)."""

    tr_id: int
    delay_pred_s: float
    delay_q10_s: float
    delay_q90_s: float
    p_late: float
    cause_code: str
    cause_confidence: float
    group_contrib_s: dict
    model_version: str
    source: str            # ml-core | ml-core:sched | fallback-rule


def rule_predict(tr_id: int, cur_dev_s: float | None) -> Result:
    """Fallback-правило ``0.6·cur_dev + 8``; интервал — Лаплас по MAE правила на test."""
    cur = cur_dev_s if cur_dev_s is not None and math.isfinite(cur_dev_s) else None
    base = cur if cur is not None else 0.0
    pred = RULE_A * base + RULE_B
    half = LAPLACE_Q90 * RULE_MAE_TEST_S
    q10, q90 = pred - half, pred + half
    if cur is None:
        code, conf = "low_data", 1.0
    else:
        d = abs(pred - base)
        code, conf = ("early", 1.0) if pred < -60 else ("accumulated", abs(base) / (abs(base) + d) if abs(base) + d else 1.0)
    return Result(tr_id, pred, q10, q90, p_late(pred, q10, q90), code, float(conf), {}, FALLBACK_VERSION,
                  "fallback-rule")


class MlClient:
    """Клиент ``ml-core`` с circuit breaker.

    Args:
        url: базовый URL (пусто — ml-core не используется, всегда fallback).
        timeout_s: таймаут запроса.
        fail_threshold: ошибок подряд до открытия breaker.
        open_s: сколько секунд breaker открыт.
    """

    def __init__(self, url: str, timeout_s: float = 1.0, fail_threshold: int = 3, open_s: float = 30.0,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.url = url.rstrip("/")
        self.transport = transport
        self.timeout_s = timeout_s
        self.fail_threshold = fail_threshold
        self.open_s = open_s
        self.failures = 0
        self.open_until = 0.0
        self.calls = 0
        self.errors = 0
        self.last_ok = False
        self.last_error: str | None = None
        self.model_version = "none"
        self.last_latency_ms: float | None = None
        self._client: httpx.AsyncClient | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.url)

    @property
    def state(self) -> str:
        if not self.enabled:
            return "disabled"
        if self.failures >= self.fail_threshold:
            return "half-open" if time.time() >= self.open_until else "open"
        return "closed"

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def predict(self, rows: list[dict], model: str = "online") -> list[Result] | None:
        """Батч в ml-core. ``None`` — ml-core недоступен (breaker открыт, таймаут, ошибка ответа)."""
        if not self.enabled or not rows or self.state == "open":
            return None
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.url, timeout=self.timeout_s, transport=self.transport)
        self.calls += 1
        t0 = time.perf_counter()
        try:
            req = PredictRequest(model=model, rows=rows)
            r = await self._client.post("/v1/predict", content=req.model_dump_json(),
                                        headers={"Content-Type": "application/json"})
            r.raise_for_status()
            resp = PredictResponse.model_validate_json(r.content)
        except Exception as e:
            self.errors += 1
            self.failures += 1
            self.last_ok = False
            self.last_error = f"{type(e).__name__}: {e}"
            if self.failures >= self.fail_threshold:
                self.open_until = time.time() + self.open_s
                log.warning("ml-core unavailable (%s), breaker open for %.0f s", self.last_error, self.open_s)
            return None
        self.last_latency_ms = (time.perf_counter() - t0) * 1000.0
        if self.failures:
            log.info("ml-core back after %d failures", self.failures)
        self.failures = 0
        self.last_ok = True
        self.last_error = None
        self.model_version = resp.model_version
        src = "ml-core" if model == "online" else f"ml-core:{model}"
        return [Result(x.tr_id, x.delay_pred_s, x.delay_q10_s, x.delay_q90_s, x.p_late, x.cause_code,
                       x.cause_confidence, dict(x.group_contrib_s), resp.model_version, src) for x in resp.results]
