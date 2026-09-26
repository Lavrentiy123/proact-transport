"""Демо бизнес-эффекта на train-дне: реальный борт и две его копии как «парк маршрута».

Копии идут тем же маршрутом со сдвигом в несколько минут, поэтому у общей остановки три машины
проходят «паровозиком». Считаем EWT по фактическим проходам (факты train — это бизнес-демо, а не
признаки модели) и после рекомендации «межрейсовая стоянка до 60 с»: догоняющая машина, у которой
интервал короче планового, задерживается на конечной на ≤ 60 с.

Запуск: ``.venv312/Scripts/python.exe -m src.product.business_demo`` → ``reports/business_demo.json``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.product.ewt import awt, ewt, swt  # noqa: E402

HOLD_MAX_S = 60.0


def passes_at_stop(real_idx: int = 9, hours=(7, 20)) -> dict:
    """Проходы реального борта ``real[real_idx]`` и его двух копий у самой «общей» остановки."""
    s = pd.read_csv(ROOT / "data" / "train" / "schedule.csv")
    s["plan"] = pd.to_datetime(s.time_begin, format="ISO8601")
    s["fact"] = pd.to_datetime(s.time_fact_begin, format="ISO8601")
    g = s.geom.str.extract(r"POINT \(([-\d.]+) ([-\d.]+)\)").astype(float)
    s["lon"], s["lat"] = g[0].round(5), g[1].round(5)
    real = sorted(set(pd.read_csv(ROOT / "data" / "labels" / "labels_test.csv").tr_id))
    ids = [real[real_idx], 9000000 + 2 * real_idx, 9000001 + 2 * real_idx]
    sub = s[s.tr_id.isin(ids) & s.fact.notna() & s.plan.dt.hour.between(hours[0], hours[1] - 1)]
    cnt = sub.groupby(["lat", "lon"]).agg(n=("tr_id", "size"), k=("tr_id", "nunique"))
    la, lo = cnt[cnt.k == 3].sort_values("n", ascending=False).index[0]
    x = sub[(sub.lat == la) & (sub.lon == lo)].sort_values("fact")
    return {"tr_ids": ids, "stop": str(x.building_address.iloc[0]), "lat": la, "lon": lo,
            "fact": x.fact.to_list(), "plan": sorted(x.plan.to_list()), "who": x.tr_id.to_list()}


def headways_min(times) -> list[float]:
    t = np.sort(pd.to_datetime(pd.Series(times)).astype("int64").to_numpy() / 1e9)
    return (np.diff(t) / 60.0).tolist()


def apply_hold(times, h_plan_min: float, hold_max_s: float = HOLD_MAX_S) -> list[pd.Timestamp]:
    """Правило рекомендации: если интервал до впереди идущей машины короче планового, догоняющая
    машина стоит на конечной min(60 с, план − интервал); проход сдвигается на это время."""
    t = sorted(pd.to_datetime(pd.Series(times)).to_list())
    out = [t[0]]
    for cur in t[1:]:
        gap = (cur - out[-1]).total_seconds()
        hold = min(hold_max_s, max(0.0, h_plan_min * 60 - gap))
        out.append(cur + pd.to_timedelta(hold, unit="s"))
    return out


# Масштаб Москвы: числа с источником и явные допущения (таблица допущений — в docs/business_effect.md)
TRIPS_PER_DAY = 3_000_000          # «более 3 млн поездок в сутки» — mskagency.ru, 31.07.2025
WAGE_RUB_MONTH = 160_700           # средняя зарплата в Москве, I кв. 2025 — kommersant.ru/doc/7757183
HOURS_PER_MONTH = 1973 / 12        # допущение: норма рабочего времени ~1973 ч/год
VOT_SHARE = 0.5                    # допущение: время ожидания ценится в 50 % часовой ставки
AFFECTED_SHARE = 0.2               # допущение: доля поездок на участках/часах со сбитыми интервалами
EFFECT_SHARE = 0.5                 # допущение: в городе эффект вдвое слабее, чем в демо


def moscow_scale(awt_reduction_min: float) -> dict:
    """Пассажиро-часы и рубли в день и в год при заданном снижении ожидания на одну поездку."""
    vot = WAGE_RUB_MONTH / HOURS_PER_MONTH * VOT_SHARE
    per_trip_min = awt_reduction_min * EFFECT_SHARE
    ph_day = TRIPS_PER_DAY * AFFECTED_SHARE * per_trip_min / 60.0
    return {"value_of_time_rub_h": vot, "saved_min_per_affected_trip": per_trip_min,
            "passenger_hours_day": ph_day, "rub_day": ph_day * vot, "rub_year": ph_day * vot * 365}


def main() -> int:
    p = passes_at_stop()
    h_fact = headways_min(p["fact"])
    h_plan_list = headways_min(p["plan"])
    h_plan = float(np.mean(h_plan_list))
    after = apply_hold(p["fact"], h_plan)
    h_after = headways_min(after)
    res = {
        "tr_ids": p["tr_ids"], "stop": p["stop"], "n_passes": len(p["fact"]),
        "h_plan_mean_min": h_plan, "h_fact_min": [round(h, 2) for h in h_fact],
        "awt_fact_min": awt(h_fact), "swt_min": swt(h_plan), "ewt_fact_min": ewt(h_fact, h_plan),
        "awt_after_min": awt(h_after), "ewt_after_min": ewt(h_after, h_plan),
        "awt_plan_min": awt(h_plan_list),
        "n_holds": int(sum(1 for a, b in zip(sorted(p["fact"]), after) if b != a)),
    }
    res["ewt_reduction_min"] = res["ewt_fact_min"] - res["ewt_after_min"]
    res["moscow"] = moscow_scale(res["awt_fact_min"] - res["awt_after_min"])
    out = ROOT / "reports" / "business_demo.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: (round(v, 2) if isinstance(v, float) else v) for k, v in res.items() if k != "h_fact_min"},
                     ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
