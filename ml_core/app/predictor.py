"""Загрузка моделей и инференс ml-core: прогноз, интервал q10–q90, P(опоздание), причина, бленд.

Модели читаются при старте приложения (:meth:`Predictor.load`), а не при импорте модуля —
так pdoc и тесты импортируют пакет без моделей.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

from ml_core.inference import (assign_causes, base_of, mlp_transform, occlusion, order_quantiles, p_late,
                               rows_to_matrix, sched_causes, to_delay)

log = logging.getLogger("ml_core")
ROOT = Path(__file__).resolve().parents[2]
REQUIRED = ("m_online", "m_online_q10", "m_online_q90", "m_sched")
LAPLACE_Q90 = float(np.log(5.0))  # квантиль 0.9 распределения Лапласа в единицах MAE


class Predictor:
    """Держит модели в памяти и считает ответы ``/v1/predict``.

    Args:
        models_dir: папка с ``feature_config.json``, ``model_card.json`` и файлами моделей.
    """

    def __init__(self, models_dir: str | Path | None = None):
        self.models_dir = Path(models_dir) if models_dir else ROOT / "models"
        self.config: dict = {}
        self.card: dict = {}
        self.models: dict = {}
        self.mlp = None          # onnxruntime-сессия PyTorch-члена (ML-T5)
        self.mlp_prep: dict = {}
        self.w_mlp = 0.0
        self.w_sched = 0.0
        self.ready = False
        self.error: str | None = None

    # ---------------- загрузка ----------------
    def load(self) -> None:
        """Читает конфиг, карточку и все модели; при ошибке ``ready = False`` и текст в ``error``."""
        from catboost import CatBoostRegressor

        try:
            self.config = json.loads((self.models_dir / "feature_config.json").read_text(encoding="utf-8"))
            card = self.models_dir / "model_card.json"
            self.card = json.loads(card.read_text(encoding="utf-8")) if card.exists() else {}
            for name in REQUIRED:
                spec = self.config["models"][name]
                m = CatBoostRegressor()
                m.load_model(blob=(self.models_dir / Path(spec["file"]).name).read_bytes())
                self.models[name] = m
            blend = self.config.get("blend", {})
            self.w_mlp = float(blend.get("w_mlp", 0.0))
            self.w_sched = float(blend.get("w_sched", 0.0))
            mlp = blend.get("mlp")
            if mlp:
                import onnxruntime as ort

                self.mlp = ort.InferenceSession((self.models_dir / Path(mlp["file"]).name).read_bytes(),
                                                providers=["CPUExecutionProvider"])
                self.mlp_prep = mlp
            self.ready = True
            self.error = None
        except Exception as e:  # сервис жив, но /ready = 503
            self.ready = False
            self.error = f"{type(e).__name__}: {e}"
            log.exception("model loading failed")

    @property
    def model_version(self) -> str:
        return self.config.get("model_version", "unknown")

    def spec(self, name: str) -> dict:
        return self.config["models"][name]

    # ---------------- члены ансамбля ----------------
    def mlp_delta(self, X: np.ndarray) -> np.ndarray:
        """Остаток Δ от PyTorch-MLP (ONNX); препроцессинг — :func:`ml_core.inference.mlp_transform`."""
        out = self.mlp.run(None, {"x": mlp_transform(X, self.mlp_prep)})[0]
        return out.reshape(-1).astype(np.float64)

    def online_delta(self, X: np.ndarray) -> np.ndarray:
        """Остаток Δ основной модели относительно базы m_online.

        Ансамбль (веса — по LOBO, ``feature_config.json → blend``) смешивает прогнозы задержки членов:
        ``ŷ = w_cat·(база + Δ_cat) + w_sched·(база_sched + Δ_sched) + w_mlp·(база + Δ_mlp)``. Базы
        считаются по столбцу ``cur_dev_s`` самой матрицы ``X`` — так окклюзия группы ``accumulated``
        честно меняет и базу.
        """
        spec = self.spec("m_online")
        names, bm = spec["features"], spec["base_mode"]
        cur = X[:, names.index("cur_dev_s")]
        base = base_of(cur, bm)
        cat = self.models["m_online"].predict(X)
        w_mlp = self.w_mlp if self.mlp is not None else 0.0
        w_sched = self.w_sched
        if w_mlp == 0.0 and w_sched == 0.0:
            return cat
        delay = (1.0 - w_mlp - w_sched) * (base + cat)
        if w_sched:
            ss = self.spec("m_sched")
            Xs = X[:, [names.index(f) for f in ss["features"]]]
            delay += w_sched * (base_of(cur, ss["base_mode"]) + self.models["m_sched"].predict(Xs))
        if w_mlp:
            delay += w_mlp * (base + self.mlp_delta(X))
        return delay - base

    # ---------------- прогноз ----------------
    def predict(self, rows: list[dict], model: str = "online") -> tuple[list[dict], int]:
        """Прогноз для батча строк ``{"tr_id": int, "features": {name: value | None}}``.

        Args:
            rows: строки запроса; отсутствующий признак → NaN, лишние игнорируются.
            model: ``online`` — m_online + квантили + причины; ``sched`` — fallback по расписанию.

        Returns:
            ``(results, n_extra)`` — словари полей ``PredictResult`` и число лишних признаков во входе.
        """
        if not rows:
            return [], 0
        feats_in = [r["features"] for r in rows]
        if model == "sched":
            return self._predict_sched(rows, feats_in)
        spec = self.spec("m_online")
        names, bm = spec["features"], spec["base_mode"]
        X, n_extra = rows_to_matrix(feats_in, names)
        cur = X[:, names.index("cur_dev_s")]
        pred, contrib, groups = occlusion(self.online_delta, X, names, self.config["norms"]["m_online"], bm)
        q10 = to_delay(cur, self.models["m_online_q10"].predict(X), self.spec("m_online_q10")["base_mode"])
        q90 = to_delay(cur, self.models["m_online_q90"].predict(X), self.spec("m_online_q90")["base_mode"])
        q10, q90 = order_quantiles(pred, q10, q90, float(self.config.get("interval_scale", 1.0)))
        pl = p_late(pred, q10, q90)
        codes, conf = assign_causes(pred, contrib, groups, X[:, names.index("tel_age_s")])
        delta = pred - base_of(cur)  # относительно cur_dev (контракт: delay = clip(cur_dev + delta))
        out = []
        for i, r in enumerate(rows):
            out.append({"tr_id": int(r["tr_id"]), "delta_pred_s": float(delta[i]), "delay_pred_s": float(pred[i]),
                        "delay_q10_s": float(q10[i]), "delay_q90_s": float(q90[i]), "p_late": float(pl[i]),
                        "cause_code": codes[i], "cause_confidence": float(conf[i]),
                        "group_contrib_s": {g: round(float(contrib[k, i]), 2) for k, g in enumerate(groups)}})
        return out, n_extra

    def _predict_sched(self, rows, feats_in) -> tuple[list[dict], int]:
        spec = self.spec("m_sched")
        names = spec["features"]
        X, n_extra = rows_to_matrix(feats_in, names)
        cur = X[:, names.index("cur_dev_s")]
        pred = to_delay(cur, self.models["m_sched"].predict(X), spec["base_mode"])
        # квантильных моделей для fallback нет: интервал по LOBO MAE m_sched (приближение Лапласа)
        half = LAPLACE_Q90 * float(self.card.get("m_sched", {}).get("lobo_mae", 90.0))
        q10, q90 = order_quantiles(pred, pred - half, pred + half)
        pl = p_late(pred, q10, q90)
        codes, conf = sched_causes(pred, cur)
        delta = pred - base_of(cur)
        out = [{"tr_id": int(r["tr_id"]), "delta_pred_s": float(delta[i]), "delay_pred_s": float(pred[i]),
                "delay_q10_s": float(q10[i]), "delay_q90_s": float(q90[i]), "p_late": float(pl[i]),
                "cause_code": codes[i], "cause_confidence": float(conf[i]), "group_contrib_s": {}}
               for i, r in enumerate(rows)]
        return out, n_extra

    def model_info(self) -> dict:
        """Ответ ``/v1/model``: версия, признаки, метрики, члены ансамбля."""
        w_mlp = self.w_mlp if self.mlp is not None else 0.0
        members = {"catboost": round(1.0 - w_mlp - self.w_sched, 3)}
        if self.w_sched:
            members["catboost_sched"] = round(self.w_sched, 3)
        if self.mlp is not None:
            members["torch_mlp_onnx"] = round(w_mlp, 3)
        return {
            "model_version": self.model_version,
            "features_version": self.config.get("features_version"),
            "ready": self.ready,
            "models": {k: {"features": v["features"], "base_mode": v["base_mode"], "iterations": v["iterations"],
                           "seeds": len(v.get("seeds", []))} for k, v in self.config.get("models", {}).items()},
            "ensemble_weights": members,
            "metrics": self.card,
        }
