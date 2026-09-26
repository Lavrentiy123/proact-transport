"""ML-T3: причины через групповую окклюзию."""
import json
import time
from pathlib import Path

import numpy as np
import pytest

from features import FEATURE_NAMES
from ml_core.inference import CAUSE_CODES, CAUSE_GROUPS, assign_causes, occlusion
from src.ml.causes import explain

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def online():
    from catboost import CatBoostRegressor

    cfg = json.loads((ROOT / "models" / "feature_config.json").read_text(encoding="utf-8"))
    m = CatBoostRegressor()
    m.load_model(str(ROOT / cfg["models"]["m_online"]["file"]))
    return m, cfg["models"]["m_online"], cfg["norms"]["m_online"]


@pytest.fixture(scope="module")
def rows30():
    from src.ml.dataset import load_features

    return load_features("test", "reconstructed").sample(30, random_state=1).reset_index(drop=True)


def test_groups_cover_all_features_except_time():
    covered = set(sum(CAUSE_GROUPS.values(), []))
    expected = set(FEATURE_NAMES) - {"tod_sin", "tod_cos", "hour"}
    assert covered == expected
    assert sum(len(v) for v in CAUSE_GROUPS.values()) == len(covered)  # без пересечений


def test_causes_codes_and_confidence(online, rows30):
    m, spec, norms = online
    out = explain(m, rows30, spec["features"], norms, spec["base_mode"])
    assert len(out) == 30
    assert set(out.cause_code) <= set(CAUSE_CODES)
    assert ((out.cause_confidence >= 0) & (out.cause_confidence <= 1)).all()
    assert np.isfinite(out.delay_pred_s).all()
    # полный прогноз совпадает с обычным predict
    from ml_core.inference import to_delay
    direct = to_delay(rows30.cur_dev_s, m.predict(rows30[spec["features"]]), spec["base_mode"])
    assert np.allclose(out.delay_pred_s, direct)


def test_causes_latency(online, rows30):
    m, spec, norms = online
    X = rows30[spec["features"]].to_numpy(float)
    explain(m, X, spec["features"], norms, spec["base_mode"])  # прогрев
    times = []
    for _ in range(10):
        t0 = time.perf_counter()
        explain(m, X, spec["features"], norms, spec["base_mode"])
        times.append(time.perf_counter() - t0)
    ms = 1000 * float(np.median(times))
    print(f"causes for 30 rows: {ms:.1f} ms")
    assert ms < 50


def test_rules_low_data_and_early():
    groups = ["congestion", "dwell", "accumulated", "hard_segment"]
    contrib = np.array([[50.0, -10.0, 5.0], [5.0, -80.0, 0.0], [10.0, -5.0, 1.0], [0.0, 0.0, 1.0]])
    pred = np.array([200.0, -100.0, 30.0])
    codes, conf = assign_causes(pred, contrib, groups, np.array([5.0, 5.0, np.nan]))
    assert codes == ["congestion", "early", "low_data"]
    assert conf[0] == pytest.approx(50 / 65)
    assert np.all((conf >= 0) & (conf <= 1))


def test_occlusion_accumulated_uses_norm_base():
    names = list(FEATURE_NAMES)
    X = np.zeros((1, len(names)))
    X[0, names.index("cur_dev_s")] = 300.0
    norms = {n: 0.0 for n in names}
    pred, contrib, groups = occlusion(lambda A: np.zeros(len(A)), X, names, norms)
    assert pred[0] == 300.0
    assert contrib[groups.index("accumulated"), 0] == 300.0
