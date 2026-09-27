"""ML-T2 (главный): OnlineVehicle на потоке даёт те же признаки, что офлайн-батч.

Фиксы двух реальных бортов test подаются по одному (включая невалидные и дубли); на каждом
``T`` из ``labels_test`` ``features_at(T)`` сравнивается с
``build_features_batch(..., 'reconstructed')``.
"""
import math

import numpy as np
import pandas as pd
import pytest

from features import FEATURE_NAMES, OnlineVehicle, build_features_batch

TOL = 1e-6


def _diff(a: dict, b: dict) -> list[str]:
    bad = []
    for k in FEATURE_NAMES:
        x, y = float(a[k]), float(b[k])
        if math.isnan(x) or math.isnan(y):
            if not (math.isnan(x) and math.isnan(y)):
                bad.append(f"{k}: online={x} offline={y}")
        elif abs(x - y) > TOL * max(1.0, abs(x), abs(y)):
            bad.append(f"{k}: online={x} offline={y}")
    return bad


def _feed_and_compare(veh, rows, pts, offline, shuffle_rng=None):
    rows = rows.reset_index(drop=True)
    order = np.arange(len(rows))
    if shuffle_rng is not None:
        # перемешиваем соседние пакеты в пределах ~1 минуты — как is_hist_data (приходят не по порядку)
        keys = rows["t"].astype("int64").to_numpy() / 1e9 + shuffle_rng.uniform(0, 60, len(rows))
        order = np.argsort(keys, kind="stable")
    t_sorted = rows["t"].to_numpy()
    n_cmp, n_tgt_mismatch, failures = 0, 0, []
    j = 0
    for p in pts.itertuples():
        T = pd.Timestamp(p.T)
        # подаём все пакеты, пришедшие «до T»; при перемешивании — по ключу прихода
        while j < len(order):
            r = rows.iloc[order[j]]
            if shuffle_rng is None and r.t > T:
                break
            if shuffle_rng is not None and keys[order[j]] > T.value / 1e9:
                break
            veh.push(r.t, r.lat, r.lon, r.speed, r.heading, bool(r.valid))
            j += 1
        if shuffle_rng is not None:
            # опоздавшие пакеты с t <= T, ещё не пришедшие, офлайн видит — досылаем их сейчас
            late = [k for k in order[j:] if t_sorted[k] <= np.datetime64(T)]
            for k in late:
                r = rows.iloc[k]
                veh.push(r.t, r.lat, r.lon, r.speed, r.heading, bool(r.valid))
            late_set = set(late)
            order = np.array([k for k in order[j:] if k not in late_set], dtype=int)
            j = 0
        tgt = veh.target_at(T)
        if tgt is None or tgt[0] != p.target_stop_id:
            n_tgt_mismatch += 1
            tgt = (p.target_stop_id, p.target_time_begin)
        f_on = veh.features_at(T, target=tgt)
        f_off = offline.loc[p.sample_id, FEATURE_NAMES].astype(float).to_dict()
        d = _diff(f_on, f_off)
        if d:
            failures.append((p.sample_id, d[:3]))
        n_cmp += 1
    return n_cmp, n_tgt_mismatch, failures


@pytest.fixture(scope="module")
def raw_test_traffic():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    raw = pd.read_csv(root / "data" / "test" / "traffic.csv", low_memory=False,
                      usecols=["tr_id", "event_time", "location_valid", "lat", "lon", "speed", "heading"])
    raw["t"] = pd.to_datetime(raw["event_time"], format="ISO8601")
    raw["valid"] = raw["location_valid"].astype(str).str.lower().eq("true") & raw.lat.notna() & raw.lon.notna()
    return raw.sort_values("t", kind="stable")


@pytest.mark.slow
@pytest.mark.parametrize("bus_i", [0, 1])
def test_online_equals_offline(test_data, raw_test_traffic, bus_i):
    buses = sorted(test_data.labels.tr_id.unique())[:2]
    tr_id = buses[bus_i]
    pts = test_data.labels[test_data.labels.tr_id == tr_id].sort_values("T").reset_index(drop=True)
    offline = build_features_batch(pts, test_data.traffic, test_data.schedule, "reconstructed").set_index("sample_id")
    veh = OnlineVehicle(test_data.schedule[test_data.schedule.tr_id == tr_id], tr_id=int(tr_id))
    rows = raw_test_traffic[raw_test_traffic.tr_id == tr_id]
    n_cmp, n_mis, failures = _feed_and_compare(veh, rows, pts, offline)
    print(f"bus {tr_id}: compared {n_cmp} points, target_at mismatches {n_mis}, failures {len(failures)}")
    assert n_cmp == len(pts) > 10
    assert n_mis <= max(2, 0.03 * n_cmp)  # ничьи по плановому времени у организаторов
    assert failures == [], failures[:3]


@pytest.mark.slow
def test_out_of_order_packets_same_features(test_data, raw_test_traffic):
    tr_id = sorted(test_data.labels.tr_id.unique())[0]
    pts = test_data.labels[test_data.labels.tr_id == tr_id].sort_values("T").reset_index(drop=True)
    offline = build_features_batch(pts, test_data.traffic, test_data.schedule, "reconstructed").set_index("sample_id")
    veh = OnlineVehicle(test_data.schedule[test_data.schedule.tr_id == tr_id], tr_id=int(tr_id))
    rows = raw_test_traffic[raw_test_traffic.tr_id == tr_id]
    n_cmp, _, failures = _feed_and_compare(veh, rows, pts, offline, shuffle_rng=np.random.default_rng(1))
    assert n_cmp == len(pts)
    assert failures == [], failures[:3]
    assert veh.n_dropped_late == 0
