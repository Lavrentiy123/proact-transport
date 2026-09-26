"""ML-T2: детектор прибытий — синтетические сценарии и точность на фактах train."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from features import ScheduleArrays, StopDetector
from features.io import times_to_epoch_s

ROOT = Path(__file__).resolve().parents[2]
LAT0, LON0 = 55.75, 37.60
M_PER_DEG_LON = 111_195.0 * np.cos(np.radians(LAT0))
M_PER_DEG_LAT = 111_195.0


def _sched(n=3, spacing_m=500.0, start="2026-01-06 10:00:00", step_min=2):
    return pd.DataFrame({
        "tr_id": 1, "stop_id": np.arange(101, 101 + n),
        "time_plan": pd.Timestamp(start) + pd.to_timedelta(np.arange(n) * step_min, unit="min"),
        "lat": LAT0, "lon": LON0 + np.arange(n) * spacing_m / M_PER_DEG_LON, "name": [f"S{i}" for i in range(n)],
    })


def _drive(det, x_from_m, x_to_m, t0, speed_ms=8.33, dt_s=5.0, lat_offset_m=0.0):
    """Едет по прямой вдоль остановок, возвращает список прибытий и времена фиксов."""
    out, times = [], []
    n = int(abs(x_to_m - x_from_m) / (speed_ms * dt_s)) + 1
    sign = 1 if x_to_m >= x_from_m else -1
    for j in range(n):
        x = x_from_m + sign * j * speed_ms * dt_s
        t = t0 + pd.to_timedelta(j * dt_s, unit="s")
        times.append((t, x))
        out += det.update(t, LAT0 + lat_offset_m / M_PER_DEG_LAT, LON0 + x / M_PER_DEG_LON, speed_ms * 3.6)
    return out, times


def test_three_stops_in_order_and_no_return():
    det = StopDetector(_sched())
    arr, times = _drive(det, -300, 1300, pd.Timestamp("2026-01-06 09:59:00"))
    assert [s for s, _ in arr] == [101, 102, 103]
    t_arr = [t for _, t in arr]
    assert t_arr == sorted(t_arr)
    assert det.i == 3
    # возврат к остановке 1: повторного прибытия нет, указатель не уходит назад
    back, _ = _drive(det, 1300, -100, times[-1][0] + pd.to_timedelta(5, unit="s"))
    assert back == []
    assert det.i == 3
    assert set(det.arrivals) == {101, 102, 103}


def test_pass_by_40m_counts_as_pass():
    det = StopDetector(_sched(n=1))
    arr, times = _drive(det, -300, 300, pd.Timestamp("2026-01-06 09:59:30"), lat_offset_m=40.0)
    assert len(arr) == 1 and arr[0][0] == 101
    # время прибытия = время фикса с минимальным расстоянием (ближайший к x=0)
    t_min = min(times, key=lambda tx: abs(tx[1]))[0]
    assert arr[0][1] == t_min
    idx, t_arr, t_det = det.records()
    assert t_det[0] > t_arr[0]  # проезд обнаруживается позже, чем произошёл


def test_far_pass_is_not_arrival():
    det = StopDetector(_sched(n=1))
    arr, _ = _drive(det, -300, 300, pd.Timestamp("2026-01-06 09:59:30"), lat_offset_m=90.0)
    assert arr == []


def test_outside_time_window_ignored():
    det = StopDetector(_sched(n=1))
    arr, _ = _drive(det, -300, 300, pd.Timestamp("2026-01-06 09:30:00"))  # на 30 мин раньше плана
    assert arr == []


def test_known_uses_detection_time():
    det = StopDetector(_sched(n=1))
    _drive(det, -300, 300, pd.Timestamp("2026-01-06 09:59:30"), lat_offset_m=40.0)
    idx, t_arr, t_det = det.records()
    assert len(det.known(t_arr[0])[0]) == 0      # прибытие произошло, но ещё не обнаружено
    assert len(det.known(t_det[0])[0]) == 1
    sid, ts, rdev = det.last_arrival()
    assert sid == 101 and abs(rdev - (t_arr[0] - times_to_epoch_s([pd.Timestamp("2026-01-06 10:00")])[0])) < 1e-6


def test_expired_stops_do_not_block_pointer():
    # первые остановки без телеметрии; борт появляется через 44 мин у 4-й
    sch4 = _sched(n=4, step_min=15)
    det = StopDetector(sch4)
    arr, _ = _drive(det, 1300, 1600, pd.Timestamp("2026-01-06 10:44:00"))
    assert [s for s, _ in arr] == [104]
    assert set(det.missed) == {101, 102, 103}


@pytest.mark.slow
def test_detector_accuracy_on_train_facts(train_data):
    facts = pd.read_csv(ROOT / "data" / "train" / "schedule.csv", usecols=["tt_action_item_id", "time_fact_begin"])
    facts["fact_s"] = times_to_epoch_s(pd.to_datetime(facts["time_fact_begin"], format="ISO8601"))
    fact_of = dict(zip(facts.tt_action_item_id, facts.fact_s))
    trk_all = train_data.traffic[train_data.traffic.valid]
    groups = {k: v for k, v in trk_all.groupby("tr_id")}
    errs, n_eligible, n_hit = [], 0, 0
    for tr_id, s in train_data.schedule.groupby("tr_id"):
        sa = ScheduleArrays(s)
        g = groups.get(tr_id)
        if g is None:
            continue
        t = times_to_epoch_s(g.t)
        lat, lon = g.lat.to_numpy(), g.lon.to_numpy()
        det = StopDetector(sa)
        for i in range(len(t)):
            det._step(float(t[i]), float(lat[i]), float(lon[i]))
        idx, t_arr, _ = det.records()
        arr = dict(zip(idx.tolist(), t_arr.tolist()))
        lo = np.searchsorted(t, sa.plan_s - 1200, "left")
        hi = np.searchsorted(t, sa.plan_s + 1500, "right")
        for k in range(len(sa)):
            f = fact_of.get(int(sa.stop_id[k]), np.nan)
            if np.isnan(f) or hi[k] <= lo[k]:
                continue
            n_eligible += 1
            if k in arr:
                n_hit += 1
                errs.append(arr[k] - f)
    errs = np.asarray(errs)
    coverage, within30, med = n_hit / n_eligible, float((np.abs(errs) < 30).mean()), float(np.median(errs))
    print(f"detector on train facts: coverage={coverage:.3f} within30={within30:.3f} "
          f"median_err={med:.1f}s MAE={np.abs(errs).mean():.1f}s n={n_eligible}")
    assert coverage >= 0.78
    assert within30 >= 0.70
    assert -20 <= med <= 10
