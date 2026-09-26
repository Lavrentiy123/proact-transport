"""Наборы признаков для обучения и сабмита с кешем в ``cache/``.

Ключ кеша — ``FEATURES_VERSION`` + md5 исходников пакета ``features/``: поменяли признаки — кеш
пересчитается сам. Точки каждого сплита строятся по телеметрии и **плановому** расписанию своего
сплита (для validate — ``schedule_plan.csv``).
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from features import FEATURE_NAMES, FEATURES_VERSION, build_features_batch, load_schedule, load_traffic  # noqa: E402

CACHE = ROOT / "cache"
DATA = ROOT / "data"
SPLITS = {
    "train": ("labels/labels_train.csv", "train/traffic.csv", "train/schedule.csv"),
    "test": ("labels/labels_test.csv", "test/traffic.csv", "test/schedule.csv"),
    "validate": ("validate/points.csv", "validate/traffic.csv", "validate/schedule_plan.csv"),
}
TOD = ["tod_sin", "tod_cos", "hour"]
M_DS_FEATURES = list(FEATURE_NAMES)
M_DS_NOTOD_FEATURES = [f for f in FEATURE_NAMES if f not in TOD]
M_ONLINE_FEATURES = [f for f in FEATURE_NAMES if f not in TOD] + ["hour_bucket"]
M_SCHED_FEATURES = ["cur_dev_s", "horizon_s", "n_stops_between", "since_last_plan_s", "lb_delay_s", "n_pending",
                    "hour_bucket"]


def features_hash() -> str:
    """md5 исходников ``features/*.py`` (первые 10 символов)."""
    h = hashlib.md5()
    for p in sorted((ROOT / "features").glob("*.py")):
        h.update(p.read_bytes())
    return h.hexdigest()[:10]


def load_points(split: str) -> pd.DataFrame:
    """Точки прогноза сплита (``sample_id`` — строка)."""
    return pd.read_csv(DATA / SPLITS[split][0], dtype={"sample_id": str})


def load_features(split: str, source: str = "official") -> pd.DataFrame:
    """Признаки точек сплита (из кеша или посчитанные заново).

    Args:
        split: ``train`` | ``test`` | ``validate``.
        source: ``official`` (подсказка ``cur_dev_s`` организаторов) | ``reconstructed`` (детектор).

    Returns:
        DataFrame ``sample_id, tr_id, T`` + ``FEATURE_NAMES`` + ``hour_bucket`` (+ ``target_delay_s``).
    """
    CACHE.mkdir(exist_ok=True)
    path = CACHE / f"feat_{FEATURES_VERSION}_{features_hash()}_{split}_{source}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    pts_csv, trf_csv, sch_csv = SPLITS[split]
    F = build_features_batch(load_points(split), load_traffic(DATA / trf_csv), load_schedule(DATA / sch_csv), source)
    F["hour_bucket"] = np.floor(F["hour"] / 3.0)
    F.to_parquet(path, index=False)
    return F


def load_pool(source: str) -> pd.DataFrame:
    """train + test labels в одной таблице (колонка ``split``) — основа LOBO и финального обучения."""
    parts = []
    for split in ("train", "test"):
        F = load_features(split, source)
        F["split"] = split
        parts.append(F)
    pool = pd.concat(parts, ignore_index=True)
    pool["T_s"] = pd.to_datetime(pool["T"]).astype("int64") / 1e9
    return pool
