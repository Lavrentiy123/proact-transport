"""Общая логика инференса: одинаковая при обучении/оценке (``src/ml``) и в сервисе ``ml-core``.

- Модели предсказывают ``Δ = задержка − база``, где база — ``cur_dev_s`` (NaN → 0, см. :func:`base_of`);
  прогноз задержки ``ŷ = clip(база + Δ̂, −400, 700)``.
- Интервал q10–q90 упорядочивается вокруг ``ŷ``; ``p_late`` — нормальное приближение по квантилям.
- Причина — групповая окклюзия: группа признаков заменяется «нормой» (медиана по спокойным
  точкам обучения, ``|y| < 60``), вклад группы ``c_g = ŷ − ŷ(группа = норма)``.
"""

from __future__ import annotations

import math
from typing import Callable

import numpy as np

from features import FEATURE_NAMES

CLIP_LO_S, CLIP_HI_S = -400.0, 700.0
LATE_THRESHOLD_S = 120.0
SIGMA_MIN_S = 20.0
Z_10_90 = 2.563  # расстояние q10–q90 у стандартного нормального распределения
TOD_FEATURES = ["tod_sin", "tod_cos", "hour"]

CAUSE_GROUPS: dict[str, list[str]] = {
    # tel_age_s (свежесть телеметрии) отнесён к динамике движения: в таблице спецификации его не было
    "congestion": ([f"v_mean_{w}m" for w in (1, 3, 5, 10)] + [f"stop_ratio_{w}m" for w in (1, 3, 5, 10)]
                   + [f"disp_{w}m" for w in (1, 3, 5, 10)]
                   + ["v_std_5m", "stop_out_zone_s_5m", "last_speed", "tel_age_s"]),
    "dwell": ["stop_in_zone_s_5m"],
    "accumulated": ["cur_dev_s", "rdev_last", "rdev_age_s", "rdev_trend5", "rdev_trend10", "lb_delay_s",
                    "n_pending", "plan_stop_nearest_dev_s", "since_last_plan_s"],
    "hard_segment": ["route_dist_m", "dist_to_target_m", "proj_delay_s", "n_stops_between", "horizon_s"],
}
CAUSE_CODES = ("congestion", "dwell", "accumulated", "hard_segment", "early", "low_data")
LOW_DATA_TEL_AGE_S = 60.0
EARLY_THRESHOLD_S = -60.0


def add_derived(row: dict) -> dict:
    """Добавляет производные признаки моделей (``hour_bucket = hour // 3``)."""
    h = row.get("hour")
    out = dict(row)
    out["hour_bucket"] = float(int(h) // 3) if h is not None and not (isinstance(h, float) and math.isnan(h)) else math.nan
    return out


def rows_to_matrix(rows: list[dict], names: list[str]) -> tuple[np.ndarray, int]:
    """Словари признаков → матрица ``N × F`` (отсутствующий или ``None`` → NaN).

    Returns:
        ``(X, n_extra)`` — матрица и число лишних (неизвестных модели) признаков во входе.
    """
    X = np.full((len(rows), len(names)), np.nan, dtype=np.float64)
    known = set(names)
    n_extra = 0
    for i, r in enumerate(rows):
        r = add_derived(r)
        for j, n in enumerate(names):
            v = r.get(n)
            if v is not None:
                X[i, j] = float(v)
        n_extra += sum(1 for k in r if k not in known and k != "hour_bucket")
    return X, n_extra


def base_of(cur_dev_s, base_mode: str = "cur_dev") -> np.ndarray:
    """База, от которой модель предсказывает остаток.

    Args:
        cur_dev_s: подсказка (официальная или восстановленная).
        base_mode: ``"cur_dev"`` — ``cur_dev_s``, а где его нет — 0 (признак ``cur_dev_s`` при этом
            остаётся NaN); ``"zero"`` — 0 (модель предсказывает задержку целиком; выбирается по LOBO,
            когда восстановленная подсказка слишком шумная).
    """
    c = np.asarray(cur_dev_s, dtype=np.float64)
    if base_mode == "zero":
        return np.zeros_like(c)
    return np.where(np.isfinite(c), c, 0.0)


def to_delay(cur_dev_s, delta, base_mode: str = "cur_dev") -> np.ndarray:
    """``ŷ = clip(база + Δ̂, −400, 700)``."""
    return np.clip(base_of(cur_dev_s, base_mode) + np.asarray(delta, dtype=np.float64), CLIP_LO_S, CLIP_HI_S)


def order_quantiles(pred, q10, q90, scale: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """``q10 = min(q10, ŷ)``, ``q90 = max(q90, ŷ)`` — интервал всегда содержит прогноз.

    Args:
        scale: калибровка ширины по LOBO (``feature_config.json → interval_scale``): расстояния
            ``ŷ − q10`` и ``q90 − ŷ`` умножаются на ``scale``, чтобы q10–q90 накрывал ~80 % фактов.
    """
    pred = np.asarray(pred, dtype=np.float64)
    lo = np.minimum(np.asarray(q10, dtype=np.float64), pred)
    hi = np.maximum(np.asarray(q90, dtype=np.float64), pred)
    return pred - scale * (pred - lo), pred + scale * (hi - pred)


def calibrate_interval_scale(y, pred, q10, q90, target: float = 0.8) -> float:
    """Минимальный множитель ширины (сетка 1.00…4.00, шаг 0.05), при котором доля ``q10 ≤ y ≤ q90`` ≥ ``target``."""
    y = np.asarray(y, dtype=np.float64)
    for s in np.arange(1.0, 4.0001, 0.05):
        lo, hi = order_quantiles(pred, q10, q90, s)
        if np.mean((y >= lo) & (y <= hi)) >= target:
            return float(round(s, 2))
    return 4.0


def p_late(pred, q10, q90, threshold_s: float = LATE_THRESHOLD_S) -> np.ndarray:
    """P(задержка > 120 с): ``σ = max((q90 − q10) / 2.563, 20)``, ``p = 1 − Φ((120 − ŷ) / σ)``."""
    pred = np.asarray(pred, dtype=np.float64)
    sigma = np.maximum((np.asarray(q90) - np.asarray(q10)) / Z_10_90, SIGMA_MIN_S)
    z = (threshold_s - pred) / sigma
    phi = 0.5 * (1.0 + np.vectorize(math.erf)(z / math.sqrt(2.0)))
    return np.clip(1.0 - phi, 0.0, 1.0)


def compute_norms(X: np.ndarray, names: list[str], y: np.ndarray, calm_s: float = 60.0) -> dict[str, float | None]:
    """«Норма» каждого признака — медиана по обучающим строкам с ``|y| < 60`` (NaN пропускаются)."""
    calm = np.abs(np.asarray(y, dtype=np.float64)) < calm_s
    out = {}
    for j, n in enumerate(names):
        col = X[calm, j]
        col = col[np.isfinite(col)]
        out[n] = float(np.median(col)) if len(col) else None
    return out


def group_indices(names: list[str]) -> dict[str, list[int]]:
    """Позиции признаков каждой группы причин в списке ``names``."""
    pos = {n: i for i, n in enumerate(names)}
    return {g: [pos[f] for f in fs if f in pos] for g, fs in CAUSE_GROUPS.items()}


def occlusion(predict_delta: Callable[[np.ndarray], np.ndarray], X: np.ndarray, names: list[str],
              norms: dict[str, float | None], base_mode: str = "cur_dev") -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Групповая окклюзия одним батчем ``(G + 1) · N`` строк.

    Args:
        predict_delta: функция ``X → Δ̂`` (CatBoost, бленд и т. п.).
        X: матрица признаков ``N × F`` в порядке ``names``.
        names: имена признаков модели.
        norms: нормы признаков (:func:`compute_norms`).
        base_mode: база остатка модели (:func:`base_of`).

    Returns:
        ``(pred, contrib, groups)``: прогноз задержки ``ŷ`` (N), вклады ``contrib`` (G × N) и имена групп.
        Для группы ``accumulated`` база ``cur_dev_s`` тоже берётся нормой («если бы накопленное
        отставание было обычным»).
    """
    n = len(X)
    gi = group_indices(names)
    groups = [g for g, idx in gi.items() if idx]
    stacked = np.tile(X, (len(groups) + 1, 1))
    for k, g in enumerate(groups, start=1):
        for j in gi[g]:
            v = norms.get(names[j])
            stacked[k * n:(k + 1) * n, j] = np.nan if v is None else v
    j_cur = names.index("cur_dev_s")
    delay = to_delay(stacked[:, j_cur], predict_delta(stacked), base_mode)
    pred = delay[:n]
    contrib = np.stack([pred - delay[k * n:(k + 1) * n] for k in range(1, len(groups) + 1)]) if groups \
        else np.zeros((0, n))
    return pred, contrib, groups


def assign_causes(pred: np.ndarray, contrib: np.ndarray, groups: list[str],
                  tel_age_s: np.ndarray) -> tuple[list[str], np.ndarray]:
    """Код и уверенность причины для каждой строки.

    Правила: ``tel_age_s`` > 60 или NaN → ``low_data``; ``ŷ < −60`` → ``early``; иначе группа с
    максимальным вкладом того же знака, что ``ŷ``; ``confidence = |c_g| / Σ|c|``.
    """
    codes, conf = [], np.zeros(len(pred))
    tel = np.asarray(tel_age_s, dtype=np.float64)
    for i in range(len(pred)):
        c = contrib[:, i] if len(groups) else np.zeros(0)
        tot = float(np.abs(c).sum())
        sign = 1.0 if pred[i] >= 0 else -1.0
        same = np.nonzero(np.sign(c) == sign)[0]
        best = int(same[np.argmax(np.abs(c[same]))]) if len(same) else (int(np.argmax(np.abs(c))) if len(c) else -1)
        share = float(abs(c[best]) / tot) if best >= 0 and tot > 0 else 0.0
        if not np.isfinite(tel[i]) or tel[i] > LOW_DATA_TEL_AGE_S:
            codes.append("low_data")
            conf[i] = 1.0
        elif pred[i] < EARLY_THRESHOLD_S:
            codes.append("early")
            conf[i] = share if share > 0 else 1.0
        else:
            codes.append(groups[best] if best >= 0 else "accumulated")
            conf[i] = share
    return codes, np.clip(conf, 0.0, 1.0)


def sched_causes(pred: np.ndarray, cur_dev_s: np.ndarray) -> tuple[list[str], np.ndarray]:
    """Причина для fallback-модели по расписанию: ``accumulated``, если известно отклонение, иначе ``low_data``.

    Уверенность ``accumulated`` — доля базы в прогнозе ``|база| / (|база| + |ŷ − база|)``.
    """
    cur = np.asarray(cur_dev_s, dtype=np.float64)
    codes, conf = [], np.zeros(len(pred))
    for i in range(len(pred)):
        if np.isfinite(cur[i]):
            codes.append("accumulated")
            d = abs(pred[i] - cur[i])
            conf[i] = abs(cur[i]) / (abs(cur[i]) + d) if abs(cur[i]) + d > 0 else 1.0
        else:
            codes.append("low_data")
            conf[i] = 1.0
    return codes, conf


assert set(sum(CAUSE_GROUPS.values(), [])) == set(FEATURE_NAMES) - set(TOD_FEATURES)


def mlp_fit_prep(X: np.ndarray, names: list[str], nan_share: float = 0.05) -> dict:
    """Препроцессинг PyTorch-члена по обучающей выборке: медианы, индикаторы пропуска, mean/std.

    Индикатор пропуска добавляется для признаков с долей NaN > 5 %; стандартизация — после
    заполнения медианой.
    """
    med = np.array([np.nanmedian(X[:, j]) if np.isfinite(X[:, j]).any() else 0.0 for j in range(X.shape[1])])
    ind = [j for j in range(X.shape[1]) if np.mean(~np.isfinite(X[:, j])) > nan_share]
    Xf = np.where(np.isfinite(X), X, med)
    mean, std = Xf.mean(axis=0), Xf.std(axis=0)
    std = np.where(std > 1e-9, std, 1.0)
    return {"features": list(names), "median": med.tolist(), "mean": mean.tolist(), "std": std.tolist(),
            "indicator_idx": ind}


def mlp_transform(X: np.ndarray, prep: dict) -> np.ndarray:
    """Матрица признаков → вход MLP (float32): ``[(x̃ − mean) / std, 1{x = NaN} по индикаторам]``."""
    X = np.asarray(X, dtype=np.float64)
    med = np.asarray(prep["median"], dtype=np.float64)
    Xf = np.where(np.isfinite(X), X, med)
    Z = (Xf - np.asarray(prep["mean"], dtype=np.float64)) / np.asarray(prep["std"], dtype=np.float64)
    idx = prep["indicator_idx"]
    miss = (~np.isfinite(X[:, idx])).astype(np.float64) if idx else np.zeros((len(X), 0))
    return np.concatenate([Z, miss], axis=1).astype(np.float32)
