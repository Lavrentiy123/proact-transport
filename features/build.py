"""Признаки точки прогноза ``(борт, T, целевая остановка)`` — одна функция офлайн и онлайн.

Все пути (``build_features``, ``build_features_batch``, ``OnlineVehicle.features_at``) сводятся
к :func:`features_from_arrays` на numpy-срезах. Телеметрия берётся только из окна
``(T − 30 мин, T]`` (как буфер онлайн), прибытия — только известные к ``T``.
Пропуск — ``NaN`` (никаких ``fillna(0)``).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .geo import haversine_m
from .io import ScheduleArrays, load_schedule, load_traffic, times_to_epoch_s, to_epoch_s
from .stop_detector import StopDetector, pending_stops

FEATURES_VERSION = "v2"  # v2: детектор — окно −6 мин, отправление на конечных, проверка направления
WINDOWS_MIN = (1, 3, 5, 10)
FEATURE_NAMES: list[str] = (
    ["cur_dev_s", "horizon_s", "tod_sin", "tod_cos", "hour",
     "n_stops_between", "since_last_plan_s",
     "rdev_last", "rdev_age_s", "rdev_trend5", "rdev_trend10", "n_pending", "lb_delay_s",
     "tel_age_s", "last_speed"]
    + [f"v_mean_{w}m" for w in WINDOWS_MIN]
    + [f"stop_ratio_{w}m" for w in WINDOWS_MIN]
    + [f"disp_{w}m" for w in WINDOWS_MIN]
    + ["v_std_5m", "dist_to_target_m", "route_dist_m", "plan_stop_nearest_dev_s", "proj_delay_s",
       "stop_in_zone_s_5m", "stop_out_zone_s_5m"]
)

LOOKBACK_S = 30 * 60.0        # окно телеметрии = буфер OnlineVehicle
STOP_SPEED_KMH = 2.0          # «стоит»
ZONE_RADIUS_M = 30.0          # зона посадки вокруг плановой остановки
DWELL_INTERVAL_CAP_S = 60.0   # один интервал между фиксами учитывается не дольше 60 с
ROUTE_CAND_BACK_S = 15 * 60.0  # кандидаты для «ближайшей плановой остановки»
V_EFF_MIN_KMH, V_EFF_DEFAULT_KMH = 5.0, 15.0
NAN = math.nan


def in_zone_flags(lat: np.ndarray, lon: np.ndarray, sched: ScheduleArrays) -> np.ndarray:
    """Для каждого фикса: ближе ли он ``ZONE_RADIUS_M`` к какой-либо плановой остановке борта."""
    out = np.zeros(len(lat), dtype=bool)
    if len(lat) == 0 or len(sched.zone_lat) == 0:
        return out
    step = max(1, 200_000 // len(sched.zone_lat))
    for a in range(0, len(lat), step):
        d = haversine_m(lon[a:a + step, None], lat[a:a + step, None], sched.zone_lon[None, :], sched.zone_lat[None, :])
        out[a:a + step] = d.min(axis=1) < ZONE_RADIUS_M
    return out


def features_from_arrays(T: float, t: np.ndarray, lat: np.ndarray, lon: np.ndarray, spd: np.ndarray,
                         sched: ScheduleArrays, target_idx: int | None, target_plan_s: float,
                         arr_idx: np.ndarray, arr_t: np.ndarray, cur_dev_s: float | None = None,
                         inzone: np.ndarray | None = None) -> dict[str, float]:
    """Ядро расчёта признаков (общее для офлайна и онлайна).

    Args:
        T: момент прогноза, секунды.
        t, lat, lon, spd: валидные фиксы борта, по возрастанию ``t``; используются только
            ``T − 30 мин < t ≤ T``.
        sched: плановое расписание борта.
        target_idx: позиция целевой остановки в ``sched`` (``None`` — неизвестна).
        target_plan_s: плановое время целевой остановки, секунды.
        arr_idx, arr_t: прибытия, известные к ``T`` (позиции в ``sched`` и времена), в порядке обнаружения.
        cur_dev_s: официальная подсказка; ``None`` — восстановить (``rdev_last``, затем
            ``plan_stop_nearest_dev_s``, иначе NaN).
        inzone: заранее посчитанные флаги зоны посадки для ``t`` (иначе считаются здесь).

    Returns:
        ``dict`` ровно с ключами :data:`FEATURE_NAMES` в их порядке.
    """
    f = dict.fromkeys(FEATURE_NAMES, NAN)
    plan = sched.plan_s
    horizon = float(target_plan_s - T)
    f["horizon_s"] = horizon
    mod = (T % 86400.0) / 60.0
    f["tod_sin"] = math.sin(2 * math.pi * mod / 1440.0)
    f["tod_cos"] = math.cos(2 * math.pi * mod / 1440.0)
    f["hour"] = float(int(mod // 60))

    # ---- расписание ----
    upto = int(np.searchsorted(plan, T, side="right"))
    f["n_stops_between"] = float(int(np.searchsorted(plan, target_plan_s, side="right")) - upto)
    if upto > 0:
        f["since_last_plan_s"] = T - float(plan[upto - 1])

    # ---- восстановленные отклонения (детектор) ----
    last_idx = None
    if len(arr_idx):
        last_idx = int(arr_idx[-1])
        rdev = arr_t - plan[arr_idx]
        f["rdev_last"] = float(rdev[-1])
        f["rdev_age_s"] = T - float(arr_t[-1])
        for w, name in ((300.0, "rdev_trend5"), (600.0, "rdev_trend10")):
            j = np.nonzero(arr_t <= T - w)[0]
            if len(j):
                f[name] = float(rdev[-1] - rdev[j[-1]])
    n_pend, lb = pending_stops(plan, last_idx, T)
    f["n_pending"] = float(n_pend)
    f["lb_delay_s"] = lb

    # ---- телеметрия (T − 30 мин, T] ----
    lo = int(np.searchsorted(t, T - LOOKBACK_S, side="right"))
    hi = int(np.searchsorted(t, T, side="right"))
    t, lat, lon, spd = t[lo:hi], lat[lo:hi], lon[lo:hi], spd[lo:hi]
    if inzone is not None:
        inzone = inzone[lo:hi]
    n = len(t)
    if n:
        f["tel_age_s"] = T - float(t[-1])
        f["last_speed"] = float(spd[-1])
        for w in WINDOWS_MIN:
            s = int(np.searchsorted(t, T - 60.0 * w, side="right"))
            if s < n:
                sw = spd[s:]
                f[f"v_mean_{w}m"] = float(sw.mean())
                f[f"stop_ratio_{w}m"] = float((sw < STOP_SPEED_KMH).mean())
                if n - s >= 2:
                    f[f"disp_{w}m"] = float(haversine_m(lon[s], lat[s], lon[-1], lat[-1]))
                if w == 5 and n - s >= 2:
                    f["v_std_5m"] = float(sw.std(ddof=1))
        # стоянки за 5 мин: в зоне остановок (посадка) и вне (затор)
        s5 = int(np.searchsorted(t, T - 300.0, side="right"))
        if s5 < n:
            zone = inzone[s5:] if inzone is not None else in_zone_flags(lat[s5:], lon[s5:], sched)
            dt = np.minimum(np.diff(t[s5:]), DWELL_INTERVAL_CAP_S)
            stopped = spd[s5:-1] < STOP_SPEED_KMH if n - s5 >= 2 else np.zeros(0, dtype=bool)
            f["stop_in_zone_s_5m"] = float(dt[stopped & zone[:-1]].sum())
            f["stop_out_zone_s_5m"] = float(dt[stopped & ~zone[:-1]].sum())

        if target_idx is not None:
            f["dist_to_target_m"] = float(haversine_m(lon[-1], lat[-1], sched.lon[target_idx], sched.lat[target_idx]))
            k0 = int(np.searchsorted(plan, T - ROUTE_CAND_BACK_S, side="left"))
            if k0 <= target_idx:
                dd = haversine_m(lon[-1], lat[-1], sched.lon[k0:target_idx + 1], sched.lat[k0:target_idx + 1])
                j = k0 + int(np.argmin(dd))
                route = float(dd[j - k0] + (sched.chain_cum_m[target_idx] - sched.chain_cum_m[j]))
                f["route_dist_m"] = route
                f["plan_stop_nearest_dev_s"] = T - float(plan[j])
                v10 = f["v_mean_10m"]
                v_eff = max(v10, V_EFF_MIN_KMH) if not math.isnan(v10) else V_EFF_DEFAULT_KMH
                f["proj_delay_s"] = route / (v_eff / 3.6) - horizon

    if cur_dev_s is None:
        cur_dev_s = f["rdev_last"] if not math.isnan(f["rdev_last"]) else f["plan_stop_nearest_dev_s"]
    f["cur_dev_s"] = float(cur_dev_s) if cur_dev_s is not None else NAN
    return f


def _track_arrays(track: pd.DataFrame) -> tuple[np.ndarray, ...]:
    """Нормализует трек одного борта (сортировка, дедуп, только валидные фиксы) в массивы."""
    tr = track if "tr_id" in track.columns else track.assign(tr_id=0)
    if "valid" not in tr.columns and "location_valid" not in tr.columns:
        tr = tr.assign(valid=True)
    tr = load_traffic(tr)
    tr = tr[tr["valid"]]
    t = times_to_epoch_s(tr["t"])
    return (t, tr["lat"].to_numpy(np.float64), tr["lon"].to_numpy(np.float64), tr["speed"].to_numpy(np.float64))


def build_features(track: pd.DataFrame, schedule, target_stop_id: int, target_time_plan, T,
                   cur_dev_s: float | None = None, arrivals=None) -> dict[str, float]:
    """Признаки одной точки прогноза.

    Args:
        track: телеметрия борта ``DataFrame[t, lat, lon, speed, heading, valid]`` (можно сырой
            фрагмент ``traffic.csv``). Строки с ``t > T`` игнорируются — утечки нет, даже если их передали.
        schedule: плановые остановки борта (DataFrame или :class:`features.io.ScheduleArrays`).
        target_stop_id: целевая остановка.
        target_time_plan: её плановое время.
        T: момент прогноза.
        cur_dev_s: официальная подсказка; ``None`` — восстановленная (как на потоке).
        arrivals: ``None`` — детектор прогоняется по треку до ``T`` внутри;
            :class:`StopDetector` — берутся его прибытия с ``t_det ≤ T``;
            ``dict[stop_id, t_arr]`` — прибытия, которые вызывающий считает известными к ``T``.

    Returns:
        ``dict`` с ключами :data:`FEATURE_NAMES` (34 признака, порядок фиксирован).
    """
    T_s = to_epoch_s(T)
    sched = schedule if isinstance(schedule, ScheduleArrays) else ScheduleArrays(schedule)
    t, lat, lon, spd = _track_arrays(track)
    keep = t <= T_s
    t, lat, lon, spd = t[keep], lat[keep], lon[keep], spd[keep]
    if arrivals is None:
        det = StopDetector(sched)
        for i in range(len(t)):
            det._step(float(t[i]), float(lat[i]), float(lon[i]))
        arr_idx, arr_t = det.known(T_s)
    elif isinstance(arrivals, StopDetector):
        arr_idx, arr_t = arrivals.known(T_s)
    else:
        items = sorted(((sched.index_of[int(s)], to_epoch_s(ta)) for s, ta in arrivals.items()
                        if int(s) in sched.index_of), key=lambda x: (x[1], x[0]))
        items = [x for x in items if x[1] <= T_s]
        arr_idx = np.asarray([x[0] for x in items], dtype=np.int64)
        arr_t = np.asarray([x[1] for x in items], dtype=np.float64)
    return features_from_arrays(T_s, t, lat, lon, spd, sched, sched.index_of.get(int(target_stop_id)),
                                to_epoch_s(target_time_plan), arr_idx, arr_t, cur_dev_s)


def build_features_batch(points_df: pd.DataFrame, traffic_df: pd.DataFrame, schedule_df: pd.DataFrame,
                         cur_dev_source: str = "official") -> pd.DataFrame:
    """Признаки для набора точек (обучение, сабмит, оценка).

    Детектор прогоняется один раз на весь трек борта; для точки ``T`` берутся прибытия с
    ``t_det ≤ T`` и фиксы ``(T − 30 мин, T]`` через ``np.searchsorted``. Расчёт — та же
    :func:`features_from_arrays`, что и в :func:`build_features` и ``OnlineVehicle``.

    Args:
        points_df: ``sample_id, tr_id, T, target_stop_id, target_time_begin, cur_dev_s``
            (+ ``target_delay_s``).
        traffic_df: телеметрия (из :func:`features.load_traffic` или сырая).
        schedule_df: плановое расписание (из :func:`features.load_schedule` или сырое).
        cur_dev_source: ``"official"`` — подсказка из ``points_df``; ``"reconstructed"`` —
            восстановленная детектором (как на потоке).

    Returns:
        DataFrame: ``sample_id, tr_id, T`` + :data:`FEATURE_NAMES` (+ ``target_delay_s``),
        строки в порядке ``points_df``.
    """
    if cur_dev_source not in ("official", "reconstructed"):
        raise ValueError(f"cur_dev_source: {cur_dev_source!r}")
    traffic = load_traffic(traffic_df)
    traffic = traffic[traffic["valid"]]
    schedule = load_schedule(schedule_df)
    pts = points_df.reset_index(drop=True)
    T_all = times_to_epoch_s(pts["T"])
    TT_all = times_to_epoch_s(pts["target_time_begin"])
    rows: list[dict | None] = [None] * len(pts)

    tr_groups = {k: v for k, v in traffic.groupby("tr_id", sort=False)}
    sc_groups = {k: v for k, v in schedule.groupby("tr_id", sort=False)}
    for tr_id, idx in pts.groupby("tr_id", sort=False).indices.items():
        sched = ScheduleArrays(sc_groups.get(tr_id, schedule.iloc[0:0]))
        trk = tr_groups.get(tr_id)
        if trk is None:
            t = lat = lon = spd = np.zeros(0)
        else:
            t = times_to_epoch_s(trk["t"])
            lat, lon, spd = (trk[c].to_numpy(np.float64) for c in ("lat", "lon", "speed"))
        det = StopDetector(sched)
        for i in range(len(t)):
            det._step(float(t[i]), float(lat[i]), float(lon[i]))
        rec_idx, rec_t, rec_det = det.records()
        # флаги зоны нужны только для 5-минутных окон точек
        t_min = float(T_all[idx].min()) - 300.0
        inzone = np.zeros(len(t), dtype=bool)
        sel = t > t_min
        inzone[sel] = in_zone_flags(lat[sel], lon[sel], sched)
        for r in idx:
            T = float(T_all[r])
            k = int(np.searchsorted(rec_det, T, side="right"))
            lo = int(np.searchsorted(t, T - LOOKBACK_S, side="right"))
            hi = int(np.searchsorted(t, T, side="right"))
            cd = float(pts.at[r, "cur_dev_s"]) if cur_dev_source == "official" else None
            f = features_from_arrays(T, t[lo:hi], lat[lo:hi], lon[lo:hi], spd[lo:hi], sched,
                                     sched.index_of.get(int(pts.at[r, "target_stop_id"])), float(TT_all[r]),
                                     rec_idx[:k], rec_t[:k], cd, inzone[lo:hi])
            rows[r] = f
    out = pd.DataFrame(rows, columns=FEATURE_NAMES)
    out.insert(0, "T", pts["T"].values)
    out.insert(0, "tr_id", pts["tr_id"].values)
    out.insert(0, "sample_id", pts["sample_id"].astype(str).values)
    if "target_delay_s" in pts.columns:
        out["target_delay_s"] = pts["target_delay_s"].values
    return out
