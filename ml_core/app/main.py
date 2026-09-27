"""FastAPI-сервис ml-core (порт 8001): ``/health``, ``/ready``, ``/v1/model``, ``/v1/predict``; Swagger — ``/docs``.

Модели контракта берутся из ``contracts/schemas.py`` (не дублируются). Модели ML загружаются при
старте приложения; пока они не загружены, ``/ready`` отвечает 503.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from contracts.schemas import PredictRequest, PredictResponse, PredictResult
from ml_core.app.predictor import Predictor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("ml_core")
predictor = Predictor()


@asynccontextmanager
async def lifespan(_: FastAPI):
    t0 = time.perf_counter()
    predictor.load()
    log.info("models loaded=%s in %.2f s, version=%s", predictor.ready, time.perf_counter() - t0,
             predictor.model_version)
    yield


app = FastAPI(
    title="ПроАкт.Транспорт — ml-core",
    description="Прогноз задержки ТС за 10–15 минут: CatBoost (+ PyTorch MLP через ONNX), интервал q10–q90, "
                "P(опоздание > 120 с), причина (групповая окклюзия).",
    version="1.0",
    lifespan=lifespan,
)


@app.get("/health", summary="Процесс жив")
def health() -> dict:
    """Всегда 200, пока процесс отвечает."""
    return {"status": "ok"}


@app.get("/ready", summary="Модели загружены")
def ready():
    """200, если все модели загружены, иначе 503 (с причиной)."""
    if predictor.ready:
        return {"status": "ready", "model_version": predictor.model_version}
    return JSONResponse(status_code=503, content={"status": "not_ready", "error": predictor.error})


@app.get("/v1/model", summary="Версия, признаки и метрики моделей")
def model_info() -> dict:
    """``model_version``, признаки каждой модели, веса ансамбля и метрики из ``model_card.json``."""
    return predictor.model_info()


@app.post("/v1/predict", response_model=PredictResponse, summary="Батч прогнозов для всех бортов тика")
def predict(req: PredictRequest):
    """``model="online"`` — m_online + квантили + причины; ``model="sched"`` — fallback по расписанию.

    Отсутствующий признак → NaN, лишние признаки игнорируются (их число пишется в лог).
    """
    t0 = time.perf_counter()
    if not predictor.ready:
        return JSONResponse(status_code=503, content={"detail": f"models not loaded: {predictor.error}"})
    if req.model not in ("online", "sched"):
        return JSONResponse(status_code=422, content={"detail": f"unknown model {req.model!r}, use online|sched"})
    rows = [{"tr_id": r.tr_id, "features": r.features} for r in req.rows]
    results, n_extra = predictor.predict(rows, req.model)
    if n_extra:
        log.info("predict: ignored %d unknown feature values in %d rows", n_extra, len(rows))
    latency_ms = (time.perf_counter() - t0) * 1000.0
    return PredictResponse(model_version=predictor.model_version, latency_ms=latency_ms,
                           results=[PredictResult(**r) for r in results])
