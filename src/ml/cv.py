"""Честная валидация: копии бортов → оригинал, LOBO по бортам, сдвиг во времени (FWD), official.

Синтетика ``9000000 + 2i`` и ``9000001 + 2i`` — копии i-го реального борта в порядке
``sorted(set(labels_test.tr_id))`` со сдвигом по времени. Копия отложенного борта в train фолда —
утечка, поэтому группа LOBO — «борт + его копии».
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

SYNTH_BASE = 9_000_000
FWD_TRAIN_END = pd.Timestamp("2026-01-06 13:45:00")
FWD_TEST_START = pd.Timestamp("2026-01-06 14:00:00")


def real_buses(labels_test: pd.DataFrame) -> list[int]:
    """13 реальных бортов в каноническом порядке ``sorted(set(labels_test.tr_id))``."""
    return sorted(int(x) for x in set(labels_test["tr_id"]))


def bus_of(tr_id: int, real: list[int]) -> int:
    """Реальный борт для ``tr_id``: копия ``9000000 + 2i`` / ``9000001 + 2i`` → ``real[i]``, реальный → сам."""
    tr_id = int(tr_id)
    if tr_id >= SYNTH_BASE:
        return real[(tr_id - SYNTH_BASE) // 2]
    return tr_id


def add_bus(df: pd.DataFrame, real: list[int]) -> pd.DataFrame:
    """Колонки ``bus`` (группа LOBO) и ``is_real``."""
    df = df.copy()
    df["bus"] = df["tr_id"].map(lambda t: bus_of(t, real)).astype(np.int64)
    df["is_real"] = df["tr_id"] < SYNTH_BASE
    return df


def _best_shift_corr(orig: pd.DataFrame, copy: pd.DataFrame, max_shift_min: int = 25) -> float:
    o = orig.sort_values("T_s")
    best = -1.0
    for s in range(-max_shift_min * 60, max_shift_min * 60 + 1, 60):
        x = np.interp(copy["T_s"].to_numpy() - s, o["T_s"].to_numpy(), o["cur_dev_s"].to_numpy(),
                      left=np.nan, right=np.nan)
        m = np.isfinite(x)
        if m.sum() > 10 and np.std(x[m]) > 0 and np.std(copy["cur_dev_s"].to_numpy()[m]) > 0:
            best = max(best, float(np.corrcoef(x[m], copy["cur_dev_s"].to_numpy()[m])[0, 1]))
    return best


def check_mapping(pool: pd.DataFrame, real: list[int], schedule_train: pd.DataFrame | None = None) -> dict:
    """Санити-проверки маппинга копий (assert).

    - 13 реальных, 26 синтетических, у каждого реального ровно 2 копии;
    - профиль ``cur_dev_s`` копии и оригинала (при лучшем сдвиге ±25 мин) коррелирует > 0.9 — первые 3 пары;
    - (если дано расписание train) набор координат остановок каждой копии совпадает с оригиналом лучше,
      чем с любым другим реальным бортом.

    Returns:
        Словарь с цифрами проверок (для отчёта).
    """
    ids = set(int(t) for t in pool["tr_id"])
    synth = sorted(t for t in ids if t >= SYNTH_BASE)
    assert len(real) == 13, len(real)
    assert len(synth) == 26, len(synth)
    per_real = pd.Series([bus_of(t, real) for t in synth]).value_counts()
    assert set(per_real.index) == set(real) and (per_real == 2).all()
    corrs = []
    for t in synth[:3]:
        corrs.append(_best_shift_corr(pool[pool.tr_id == bus_of(t, real)], pool[pool.tr_id == t]))
    assert all(c > 0.9 for c in corrs), corrs
    out = {"n_real": len(real), "n_synth": len(synth), "corr_first3": [round(c, 3) for c in corrs]}
    if schedule_train is not None:
        S = {k: set(zip(v.lat.round(6), v.lon.round(6))) for k, v in schedule_train.groupby("tr_id")}
        hits = 0
        for t in synth:
            jac = {r: len(S[t] & S[r]) / max(1, len(S[t] | S[r])) for r in real}
            hits += max(jac, key=jac.get) == bus_of(t, real)
        assert hits == 26, hits
        out["geometry_match"] = f"{hits}/26"
    return out


def lobo_folds(pool: pd.DataFrame, n_splits: int = 13) -> list[tuple[np.ndarray, np.ndarray]]:
    """LOBO: ``GroupKFold(13)`` по ``bus`` на реальных точках.

    Returns:
        Список ``(train_idx, test_idx)`` — позиции в ``pool``. Train — все точки (реальные и копии),
        чей ``bus`` не отложен; test — реальные точки отложенного борта.
    """
    real_idx = np.nonzero(pool["is_real"].to_numpy())[0]
    groups = pool["bus"].to_numpy()
    folds = []
    for _, te in GroupKFold(n_splits=n_splits).split(real_idx, groups=groups[real_idx]):
        test_idx = real_idx[te]
        held = set(groups[test_idx])
        train_idx = np.nonzero(~np.isin(groups, list(held)))[0]
        folds.append((train_idx, test_idx))
    return folds


def fwd_split(pool: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Сдвиг во времени: обучение ``T < 13:45`` (все точки), тест — реальные точки ``T ≥ 14:00``."""
    T = pd.to_datetime(pool["T"])
    tr = np.nonzero((T < FWD_TRAIN_END).to_numpy())[0]
    te = np.nonzero(((T >= FWD_TEST_START) & pool["is_real"]).to_numpy())[0]
    return tr, te


def official_split(pool: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Официальное разбиение организаторов: train labels → test labels (только для сравнения с LB)."""
    return np.nonzero((pool["split"] == "train").to_numpy())[0], np.nonzero((pool["split"] == "test").to_numpy())[0]
