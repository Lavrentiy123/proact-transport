"""Причины прогноза: групповая окклюзия (офлайн-обёртка над ``ml_core.inference``).

Логика одна и та же в оценке и в сервисе ``ml-core`` — она живёт в :mod:`ml_core.inference`
(образ ml-core не содержит ``src/``). Здесь — удобная обёртка для CatBoost-моделей и DataFrame.

Группы (``cause_code``): ``congestion``, ``dwell``, ``accumulated``, ``hard_segment``; правила-исключения:
``low_data`` (``tel_age_s`` > 60 или NaN) и ``early`` (``ŷ < −60``).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ml_core.inference import (CAUSE_CODES, CAUSE_GROUPS, assign_causes, compute_norms, group_indices,  # noqa: F401
                               occlusion, sched_causes)


def explain(model, X: pd.DataFrame | np.ndarray, feats: list[str], norms: dict, base_mode: str = "cur_dev",
            predict_delta=None) -> pd.DataFrame:
    """Прогноз и причина для каждой строки одним батчем ``(G + 1) · N``.

    Args:
        model: модель с ``predict`` (CatBoost), предсказывает остаток Δ.
        X: признаки в порядке ``feats``.
        feats: имена признаков модели.
        norms: нормы признаков (``feature_config.json → norms``).
        base_mode: база остатка модели.
        predict_delta: своя функция ``X → Δ̂`` (например, бленд); по умолчанию ``model.predict``.

    Returns:
        DataFrame: ``delay_pred_s, cause_code, cause_confidence`` и ``contrib_<группа>`` (секунды).
    """
    Xn = X[feats].to_numpy(np.float64) if isinstance(X, pd.DataFrame) else np.asarray(X, dtype=np.float64)
    fn = predict_delta or model.predict
    pred, contrib, groups = occlusion(fn, Xn, feats, norms, base_mode)
    tel = Xn[:, feats.index("tel_age_s")] if "tel_age_s" in feats else np.full(len(Xn), np.nan)
    codes, conf = assign_causes(pred, contrib, groups, tel)
    out = pd.DataFrame({"delay_pred_s": pred, "cause_code": codes, "cause_confidence": conf})
    for k, g in enumerate(groups):
        out[f"contrib_{g}"] = contrib[k]
    return out
