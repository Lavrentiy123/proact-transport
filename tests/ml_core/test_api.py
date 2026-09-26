"""ML-T4: API ml-core через FastAPI TestClient."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

from contracts.schemas import PredictResponse
from features import build_features_batch, features_to_json
from ml_core.inference import CAUSE_CODES, CLIP_HI_S, CLIP_LO_S

SCHED_ONLY = ["cur_dev_s", "horizon_s", "n_stops_between", "since_last_plan_s", "lb_delay_s", "n_pending", "hour"]


@pytest.fixture(scope="module")
def client():
    from ml_core.app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def rows30(test_data):
    pts = test_data.labels.sample(30, random_state=2).reset_index(drop=True)
    F = build_features_batch(pts, test_data.traffic, test_data.schedule, "reconstructed")
    from features import FEATURE_NAMES

    return [{"tr_id": int(r.tr_id), "features": features_to_json({k: getattr(r, k) for k in FEATURE_NAMES})}
            for r in F.itertuples()]


def test_health_ready_model(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").status_code == 200
    info = client.get("/v1/model").json()
    assert info["model_version"].startswith("m_online-v1-")
    assert "m_online" in info["models"] and "metrics" in info


def test_predict_online_30(client, rows30):
    r = client.post("/v1/predict", json={"model": "online", "rows": rows30})
    assert r.status_code == 200
    resp = PredictResponse.model_validate(r.json())
    assert len(resp.results) == 30
    for row, res in zip(rows30, resp.results):
        cur = row["features"]["cur_dev_s"]
        base = cur if cur is not None else 0.0
        assert res.tr_id == row["tr_id"]
        assert res.delay_pred_s == pytest.approx(float(np.clip(base + res.delta_pred_s, CLIP_LO_S, CLIP_HI_S)), abs=1e-6)
        assert 0.0 <= res.p_late <= 1.0
        assert res.delay_q10_s <= res.delay_pred_s <= res.delay_q90_s
        assert res.cause_code in CAUSE_CODES
        assert 0.0 <= res.cause_confidence <= 1.0
    lat = [client.post("/v1/predict", json={"model": "online", "rows": rows30}).json()["latency_ms"] for _ in range(7)]
    print(f"/v1/predict latency for 30 rows: best {np.min(lat):.1f} ms, median {np.median(lat):.1f} ms")
    # лучший из 7: на перегруженном ноутбуке медиана отражает чужую нагрузку (в покое ~27 мс на 30 строк)
    assert np.min(lat) < 100


def test_predict_sched_without_telemetry(client, rows30):
    rows = [{"tr_id": r["tr_id"], "features": {k: r["features"][k] for k in SCHED_ONLY}} for r in rows30[:10]]
    r = client.post("/v1/predict", json={"model": "sched", "rows": rows})
    assert r.status_code == 200
    res = PredictResponse.model_validate(r.json()).results
    assert len(res) == 10
    assert {x.cause_code for x in res} <= {"accumulated", "low_data"}
    assert all(x.delay_q10_s <= x.delay_pred_s <= x.delay_q90_s for x in res)


def test_missing_and_extra_features(client, rows30):
    feats = dict(rows30[0]["features"])
    feats.pop("v_mean_1m")
    feats["some_unknown_feature"] = 1.0
    r = client.post("/v1/predict", json={"rows": [{"tr_id": 1, "features": feats}]})
    assert r.status_code == 200 and len(r.json()["results"]) == 1


def test_empty_batch(client):
    r = client.post("/v1/predict", json={"model": "online", "rows": []})
    assert r.status_code == 200
    assert r.json()["results"] == []


def test_bad_body(client):
    assert client.post("/v1/predict", json={"rows": "not-a-list"}).status_code == 422
    assert client.post("/v1/predict", json={"rows": [{"features": {}}]}).status_code == 422
