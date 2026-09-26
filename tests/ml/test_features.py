"""ML-T2: признаки — анти-утечка, batch == single, состав и производительность."""
import math
import time

import numpy as np
import pandas as pd
import pytest

from features import (FEATURE_NAMES, FEATURES_VERSION, OnlineVehicle, build_features, build_features_batch,
                      to_epoch_s)


def _same(a: dict, b: dict, tol: float = 1e-9) -> list[str]:
    bad = []
    for k in FEATURE_NAMES:
        x, y = a[k], b[k]
        if (isinstance(x, float) and math.isnan(x)) or (isinstance(y, float) and math.isnan(y)):
            if not (math.isnan(x) and math.isnan(y)):
                bad.append(f"{k}: {x} vs {y}")
        elif abs(x - y) > tol * max(1.0, abs(x), abs(y)):
            bad.append(f"{k}: {x} vs {y}")
    return bad


@pytest.fixture(scope="module")
def sample_points(test_data):
    return test_data.labels.sample(50, random_state=0).reset_index(drop=True)


def test_feature_names_fixed():
    assert len(FEATURE_NAMES) == 34
    assert len(set(FEATURE_NAMES)) == 34
    assert FEATURES_VERSION == "v1"


def test_build_features_keys(test_data):
    p = test_data.labels.iloc[10]
    trk = test_data.traffic[test_data.traffic.tr_id == p.tr_id]
    sch = test_data.schedule[test_data.schedule.tr_id == p.tr_id]
    f = build_features(trk, sch, p.target_stop_id, p.target_time_begin, p["T"], p.cur_dev_s)
    assert list(f.keys()) == FEATURE_NAMES
    assert len(f) == 34


def test_epoch_is_naive_time_as_utc(test_data):
    p = test_data.labels.iloc[0]
    assert int(p.sample_id.split("_")[1]) == int(to_epoch_s(p["T"]))
    assert to_epoch_s("2026-01-06 03:35:00") == 1767670500.0


def test_no_leakage_future_track_is_ignored(test_data, sample_points):
    rng = np.random.default_rng(0)
    for p in sample_points.itertuples():
        trk = test_data.traffic[test_data.traffic.tr_id == p.tr_id]
        sch = test_data.schedule[test_data.schedule.tr_id == p.tr_id]
        T = pd.Timestamp(p.T)
        cut = trk[trk.t <= T]
        garbage = pd.DataFrame({
            "tr_id": p.tr_id, "t": T + pd.to_timedelta(rng.integers(1, 3600, 200), unit="s"),
            "lat": rng.uniform(55.5, 56.0, 200), "lon": rng.uniform(37.3, 37.9, 200),
            "speed": rng.uniform(0, 60, 200), "heading": 0.0, "valid": True, "unit_id": -1,
        })
        args = (sch, p.target_stop_id, p.target_time_begin, p.T)
        f_full = build_features(trk, *args)
        f_cut = build_features(cut, *args)
        f_garb = build_features(pd.concat([cut, garbage], ignore_index=True), *args)
        assert _same(f_full, f_cut) == [], p.sample_id
        assert _same(f_full, f_garb) == [], p.sample_id


def test_batch_equals_single(test_data, sample_points):
    batch = build_features_batch(sample_points, test_data.traffic, test_data.schedule, "official")
    assert list(batch.columns[:3]) == ["sample_id", "tr_id", "T"]
    assert list(batch.columns[3:37]) == FEATURE_NAMES
    for i, p in enumerate(sample_points.itertuples()):
        trk = test_data.traffic[test_data.traffic.tr_id == p.tr_id]
        sch = test_data.schedule[test_data.schedule.tr_id == p.tr_id]
        single = build_features(trk, sch, p.target_stop_id, p.target_time_begin, p.T, p.cur_dev_s)
        row = batch.iloc[i][FEATURE_NAMES].astype(float).to_dict()
        assert batch.iloc[i].sample_id == p.sample_id
        assert _same(single, row, 1e-9) == [], p.sample_id


def test_reconstructed_cur_dev_rule(test_data, sample_points):
    b = build_features_batch(sample_points, test_data.traffic, test_data.schedule, "reconstructed")
    exp = b.rdev_last.where(b.rdev_last.notna(), b.plan_stop_nearest_dev_s)
    assert np.allclose(b.cur_dev_s, exp, equal_nan=True)


def test_features_at_latency(test_data):
    tr_id = int(test_data.labels.tr_id.iloc[0])
    trk = test_data.traffic[(test_data.traffic.tr_id == tr_id) & test_data.traffic.valid]
    veh = OnlineVehicle(test_data.schedule[test_data.schedule.tr_id == tr_id], tr_id=tr_id)
    T_end = pd.Timestamp("2026-01-06 12:00:00")
    for r in trk[trk.t <= T_end].itertuples():
        veh.push(r.t, r.lat, r.lon, r.speed, r.heading, True)
    T = T_end
    while veh.target_at(T) is None:
        T -= pd.Timedelta(seconds=30)
    times = []
    for _ in range(200):
        t0 = time.perf_counter()
        f = veh.features_at(T)
        times.append(time.perf_counter() - t0)
    assert f is not None and list(f) == FEATURE_NAMES
    p50_ms = 1000 * float(np.median(times))
    print(f"features_at p50 = {p50_ms:.2f} ms")
    assert p50_ms < 5.0


@pytest.mark.slow
def test_batch_train_performance(train_data):
    t0 = time.perf_counter()
    F = build_features_batch(train_data.labels, train_data.traffic, train_data.schedule, "official")
    dt = time.perf_counter() - t0
    print(f"build_features_batch train: {len(F)} points in {dt:.1f} s")
    assert len(F) == len(train_data.labels) == 4434
    assert dt < 90
