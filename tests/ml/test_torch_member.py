"""ML-T5: PyTorch-член ансамбля — ONNX == torch, бленд в ml-core == офлайн, латентность, веса в /v1/model."""
import json
import time
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
torch = pytest.importorskip("torch")


@pytest.fixture(scope="module")
def cfg():
    return json.loads((ROOT / "models" / "feature_config.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def X100(cfg):
    from src.ml.dataset import load_features

    F = load_features("test", "reconstructed").sample(100, random_state=3)
    return F[cfg["models"]["m_online"]["features"]].to_numpy(np.float64)


@pytest.fixture(scope="module")
def session(cfg):
    from ml_core.app.predictor import onnx_session

    return onnx_session((ROOT / cfg["blend"]["mlp"]["file"]).read_bytes())  # как в ml-core


def test_onnx_equals_torch(cfg, X100, session):
    from ml_core.inference import mlp_transform
    from src.ml.torch_mlp import MLP, SeedEnsemble, train_one

    prep = cfg["blend"]["mlp"]
    Z = mlp_transform(X100, prep)
    # собираем torch-ансамбль тем же кодом и сверяем с ONNX, экспортированным из него
    from src.ml.torch_mlp import export_onnx

    rng = np.random.default_rng(0)
    members = [train_one(Z, rng.normal(0, 50, len(Z)), s) for s in (0, 1)]
    import onnxruntime as ort

    sess = ort.InferenceSession(export_onnx(members, Z.shape[1]), providers=["CPUExecutionProvider"])
    with torch.no_grad():
        ref = SeedEnsemble(members).eval()(torch.from_numpy(Z)).numpy().reshape(-1)
    out = sess.run(None, {"x": Z})[0].reshape(-1)
    assert np.max(np.abs(out - ref)) < 1e-4
    # и боевая ONNX-модель считает конечные числа нужной формы
    prod = session.run(None, {"x": Z})[0]
    assert prod.shape == (100, 1) and np.isfinite(prod).all()
    assert isinstance(members[0], MLP)


def test_blend_in_ml_core_equals_offline(cfg, X100, session):
    from catboost import CatBoostRegressor

    from ml_core.app.predictor import Predictor
    from ml_core.inference import base_of, mlp_transform

    p = Predictor()
    p.load()
    assert p.ready
    blend = cfg["blend"]
    wm, ws = blend["w_mlp"], blend.get("w_sched", 0.0)
    spec, ss = cfg["models"]["m_online"], cfg["models"]["m_sched"]
    names = spec["features"]
    cur = X100[:, names.index("cur_dev_s")]
    base = base_of(cur, spec["base_mode"])
    cat = CatBoostRegressor()
    cat.load_model(str(ROOT / spec["file"]))
    sched = CatBoostRegressor()
    sched.load_model(str(ROOT / ss["file"]))
    mlp = session.run(None, {"x": mlp_transform(X100, blend["mlp"])})[0].reshape(-1)
    d_sched = sched.predict(X100[:, [names.index(f) for f in ss["features"]]])
    offline = ((1 - wm - ws) * (base + cat.predict(X100)) + ws * (base_of(cur, ss["base_mode"]) + d_sched)
               + wm * (base + mlp)) - base
    assert np.max(np.abs(p.online_delta(X100) - offline)) < 1e-6


def test_onnx_latency_batch30(cfg, X100, session):
    from ml_core.inference import mlp_transform

    Z = mlp_transform(X100[:30], cfg["blend"]["mlp"])
    session.run(None, {"x": Z})
    times = []
    for _ in range(50):
        t0 = time.perf_counter()
        session.run(None, {"x": Z})
        times.append(time.perf_counter() - t0)
    p50 = 1000 * float(np.median(times))
    print(f"ONNX MLP batch 30: p50 {p50:.3f} ms")
    assert p50 < 5


def test_model_endpoint_shows_ensemble_weights(cfg):
    from fastapi.testclient import TestClient

    from ml_core.app.main import app

    with TestClient(app) as c:
        info = c.get("/v1/model").json()
    weights = info["ensemble_weights"]
    assert {"catboost", "torch_mlp_onnx"} <= set(weights)
    assert weights["torch_mlp_onnx"] == pytest.approx(cfg["blend"]["w_mlp"])
    assert weights.get("catboost_sched", 0.0) == pytest.approx(cfg["blend"].get("w_sched", 0.0))
    assert sum(weights.values()) == pytest.approx(1.0)
