"""ML-T3: маппинг копий, LOBO без утечки, модели загружаются и предсказывают, сабмиты валидны."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from src.ml.cv import add_bus, bus_of, fwd_split, lobo_folds, official_split, real_buses  # noqa: E402

CFG_PATH = ROOT / "models" / "feature_config.json"
CARD_PATH = ROOT / "models" / "model_card.json"


@pytest.fixture(scope="module")
def real():
    return real_buses(pd.read_csv(ROOT / "data" / "labels" / "labels_test.csv"))


@pytest.fixture(scope="module")
def pool(real):
    lb = pd.read_csv(ROOT / "data" / "labels" / "labels_train.csv", dtype={"sample_id": str}).assign(split="train")
    lt = pd.read_csv(ROOT / "data" / "labels" / "labels_test.csv", dtype={"sample_id": str}).assign(split="test")
    return add_bus(pd.concat([lb, lt], ignore_index=True), real)


@pytest.fixture(scope="module")
def cfg():
    return json.loads(CFG_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rows30():
    from src.ml.dataset import load_features

    return load_features("test", "reconstructed").sample(30, random_state=0).reset_index(drop=True)


def test_bus_of(real):
    assert len(real) == 13
    assert bus_of(9000000, real) == real[0] and bus_of(9000001, real) == real[0]
    assert bus_of(9000025, real) == real[12]
    assert bus_of(real[5], real) == real[5]


def test_lobo_no_leakage(pool):
    folds = lobo_folds(pool)
    assert len(folds) == 13
    seen = []
    for tr, te in folds:
        held = set(pool.bus.iloc[te])
        assert len(held) == 1
        assert pool.is_real.iloc[te].all()
        # ни точки отложенного борта, ни его копий
        assert not held & set(pool.bus.iloc[tr])
        seen += list(te)
    assert sorted(seen) == sorted(np.nonzero(pool.is_real.to_numpy())[0])


def test_fwd_and_official_splits(pool):
    tr, te = fwd_split(pool)
    T = pd.to_datetime(pool["T"])
    assert T.iloc[tr].max() < pd.Timestamp("2026-01-06 13:45") <= pd.Timestamp("2026-01-06 14:00") <= T.iloc[te].min()
    tr, te = official_split(pool)
    assert (pool.split.iloc[tr] == "train").all() and (pool.split.iloc[te] == "test").all()


def test_models_load_and_predict(cfg, rows30):
    from catboost import CatBoostRegressor

    from src.ml.dataset import load_features

    off = load_features("test", "official").sample(30, random_state=0)
    for name, m in cfg["models"].items():
        model = CatBoostRegressor()
        model.load_model(str(ROOT / m["file"]))
        X = (off if m["cur_dev_source"] == "official" else rows30)[m["features"]]
        p = model.predict(X)
        assert len(p) == 30 and np.isfinite(p).all(), name


def test_quantiles_ordered(cfg, rows30):
    from catboost import CatBoostRegressor

    from ml_core.inference import order_quantiles, p_late, to_delay

    preds = {}
    for name in ("m_online", "m_online_q10", "m_online_q90"):
        m = CatBoostRegressor()
        m.load_model(str(ROOT / cfg["models"][name]["file"]))
        preds[name] = to_delay(rows30.cur_dev_s, m.predict(rows30[cfg["models"][name]["features"]]),
                               cfg["models"][name]["base_mode"])
    q10, q90 = order_quantiles(preds["m_online"], preds["m_online_q10"], preds["m_online_q90"])
    assert np.all(q10 <= preds["m_online"]) and np.all(preds["m_online"] <= q90)
    pl = p_late(preds["m_online"], q10, q90)
    assert np.all((pl >= 0) & (pl <= 1))


def test_feature_config_contents(cfg):
    from features import FEATURES_VERSION

    assert cfg["features_version"] == FEATURES_VERSION
    assert cfg["model_version"].startswith("m_online-v1-")
    for name in ("m_ds", "m_online", "m_online_q10", "m_online_q90", "m_sched"):
        assert name in cfg["models"]
    assert set(cfg["norms"]["m_online"]) == set(cfg["models"]["m_online"]["features"])
    assert not (ROOT / "models" / "catboost_delta_predictor.cbm").exists()


def test_acceptance_thresholds():
    card = json.loads(CARD_PATH.read_text(encoding="utf-8"))
    assert card["m_ds"]["official_mae"] <= 63
    assert card["m_ds"]["lobo_mae"] <= 77
    assert card["m_online"]["lobo_mae"] <= card["m_ds"]["lobo_mae"] + 10
    assert card["m_sched"]["lobo_mae"] <= card["baselines"]["lobo_cur_dev_reconstructed"] - 3


def test_submissions_valid():
    from src.validate_submission import validate

    journal = pd.read_csv(ROOT / "submissions" / "journal.csv")
    subs = journal[journal.model.str.startswith("m_ds")]
    assert len(subs) >= 3
    for f in subs.file:
        assert validate(ROOT / f) == [], f
