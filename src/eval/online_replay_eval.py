"""Онлайн-replay дня test: горизонт прогнозов и онлайн-MAE (доказательство для критерия 2).

Фиксы реальных бортов подаются по времени в ``OnlineVehicle`` (как с потока NDTP); на тиках каждые
5 минут (сетка T датасета) и каждые 60 с: ``target_at(T)`` → ``features_at(T)`` → предиктор ml-core
локально (без HTTP). Факт прибытия берётся из ``test/schedule.csv`` — здесь это **оценка**, а не
признак (поэтому скрипт лежит в ``src/eval/``, а не в ``src/ml/``).

Запуск: ``.venv312/Scripts/python.exe -m src.eval.online_replay_eval`` → ``reports/online_eval.md`` и
раздел ``online_eval`` в ``models/model_card.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from features import OnlineVehicle, features_to_json, load_schedule, to_epoch_s  # noqa: E402
from features.io import times_to_epoch_s  # noqa: E402
from ml_core.app.predictor import Predictor  # noqa: E402
from ml_core.inference import base_of  # noqa: E402

DATA = ROOT / "data"


def load_facts() -> dict[int, float]:
    """``stop_id → фактическая задержка, с`` по ``test/schedule.csv`` (только для оценки)."""
    s = pd.read_csv(DATA / "test" / "schedule.csv", usecols=["tt_action_item_id", "time_begin", "time_fact_begin"])
    plan = times_to_epoch_s(pd.to_datetime(s["time_begin"], format="ISO8601"))
    fact = times_to_epoch_s(pd.to_datetime(s["time_fact_begin"], format="ISO8601"))
    return dict(zip(s["tt_action_item_id"].astype(np.int64), fact - plan))


def run_replay(tr_ids: list[int] | None = None, tick_s: int = 60, predictor: Predictor | None = None) -> pd.DataFrame:
    """Прогоняет день test через ``OnlineVehicle`` и предиктор.

    Args:
        tr_ids: борта (по умолчанию — все реальные борта test из ``labels_test``).
        tick_s: шаг тика, с (300 — сетка датасета, 60 — поминутно).
        predictor: загруженный :class:`ml_core.app.predictor.Predictor` (иначе создаётся).

    Returns:
        Журнал тиков: ``issued_at, tr_id, built, stop_id, lead_s, pred, q10, q90, p_late, cause, cur_dev_rec,
        feat_ms, pred_ms, fact_delay_s``.
    """
    if predictor is None:
        predictor = Predictor()
        predictor.load()
    labels = pd.read_csv(DATA / "labels" / "labels_test.csv")
    buses = tr_ids or sorted(int(x) for x in labels.tr_id.unique())
    sched = load_schedule(DATA / "test" / "schedule.csv")
    raw = pd.read_csv(DATA / "test" / "traffic.csv", low_memory=False,
                      usecols=["tr_id", "event_time", "location_valid", "lat", "lon", "speed", "heading"])
    raw = raw[raw.tr_id.isin(buses)].copy()
    raw["t"] = times_to_epoch_s(pd.to_datetime(raw["event_time"], format="ISO8601"))
    raw["valid"] = raw["location_valid"].astype(str).str.lower().eq("true") & raw.lat.notna() & raw.lon.notna()
    raw = raw.sort_values("t", kind="stable")
    facts = load_facts()
    veh = {b: OnlineVehicle(sched[sched.tr_id == b], tr_id=b) for b in buses}

    t_first, t_last = float(raw.t.iloc[0]), float(raw.t.iloc[-1])
    ticks = np.arange(np.ceil(t_first / tick_s) * tick_s, t_last + 1, tick_s)
    rec = []
    rows = raw[["tr_id", "t", "lat", "lon", "speed", "heading", "valid"]].to_numpy(object)
    j = 0
    for T in ticks:
        while j < len(rows) and rows[j][1] <= T:
            b, t, la, lo, sp, hd, ok = rows[j]
            veh[b].push(float(t), float(la), float(lo), float(sp), float(hd), bool(ok))
            j += 1
        batch, meta = [], []
        for b in buses:
            v = veh[b]
            t0 = time.perf_counter()
            tgt = v.target_at(T)
            f = v.features_at(T, target=tgt) if tgt is not None else None
            ms = (time.perf_counter() - t0) * 1000
            if f is None:
                rec.append({"issued_at": T, "tr_id": b, "built": False, "feat_ms": ms})
                continue
            batch.append({"tr_id": b, "features": features_to_json(f)})
            meta.append((b, tgt, f, ms))
        if not batch:
            continue
        t0 = time.perf_counter()
        res, _ = predictor.predict(batch, "online")
        pred_ms = (time.perf_counter() - t0) * 1000
        for (b, tgt, f, ms), r in zip(meta, res):
            plan_s = to_epoch_s(tgt[1])
            rec.append({"issued_at": T, "tr_id": b, "built": True, "stop_id": int(tgt[0]), "lead_s": plan_s - T,
                        "pred": r["delay_pred_s"], "q10": r["delay_q10_s"], "q90": r["delay_q90_s"],
                        "p_late": r["p_late"], "cause": r["cause_code"],
                        "cur_dev_rec": float(base_of([f["cur_dev_s"]])[0]),
                        "feat_ms": ms, "pred_ms": pred_ms / len(batch), "batch": len(batch),
                        "fact_delay_s": facts.get(int(tgt[0]), np.nan)})
    return pd.DataFrame(rec)


def early_warning(res: pd.DataFrame, late_s: float = 120.0) -> dict:
    """Ранние предупреждения и отсутствие прогнозов «задним числом» (по фактам, только оценка).

    ``actual_lead`` — сколько секунд от выдачи прогноза до ФАКТИЧЕСКОГО прибытия (план + фактическая задержка).
    Прогноз задним числом — ``actual_lead ≤ 0``. Опоздание — фактическая задержка > 120 с (порог late датасета).
    """
    if not len(res):
        return {}
    actual_lead = res.lead_s + res.fact_delay_s
    late = res.fact_delay_s > late_s
    warned = res.pred > late_s
    return {
        "share_issued_before_actual_arrival": float((actual_lead > 0).mean()),
        "actual_lead_min_s": float(actual_lead.min()),
        "actual_lead_p50_s": float(actual_lead.median()),
        "late_events": int(late.sum()),
        "late_warned_share": float(warned[late].mean()) if late.any() else float("nan"),
        "warning_precision": float(late[warned].mean()) if warned.any() else float("nan"),
        "late_p_late_mean": float(res.p_late[late].mean()) if late.any() else float("nan"),
        "ontime_p_late_mean": float(res.p_late[~late].mean()) if (~late).any() else float("nan"),
    }


def summarize(log: pd.DataFrame) -> dict:
    """Метрики журнала тиков: горизонт, покрытие, онлайн-MAE против бейзлайна, причины, время на борт."""
    built = log[log.built]
    res = built[np.isfinite(built.fact_delay_s)]
    per_bus_ms = built.feat_ms + built.pred_ms
    return {
        "ticks_total": int(len(log)),
        "forecasts_total": int(len(built)),
        "coverage": float(len(built) / max(1, len(log))),
        "share_lead_in_window": float(((built.lead_s >= 600) & (built.lead_s <= 900)).mean()) if len(built) else float("nan"),
        "resolved_total": int(len(res)),
        "online_mae_model_s": float(np.abs(res.pred - res.fact_delay_s).mean()) if len(res) else float("nan"),
        "online_mae_baseline_s": float(np.abs(res.cur_dev_rec - res.fact_delay_s).mean()) if len(res) else float("nan"),
        "online_mae_zero_s": float(np.abs(res.fact_delay_s).mean()) if len(res) else float("nan"),
        "interval_coverage": float(((res.fact_delay_s >= res.q10) & (res.fact_delay_s <= res.q90)).mean()) if len(res) else float("nan"),
        "causes_pct": {k: round(100 * v, 1) for k, v in built.cause.value_counts(normalize=True).items()},
        **early_warning(res),
        "per_bus_ms_p50": float(np.percentile(per_bus_ms, 50)) if len(built) else float("nan"),
        "per_bus_ms_p99": float(np.percentile(per_bus_ms, 99)) if len(built) else float("nan"),
        "buses": int(log.tr_id.nunique()),
    }


def out_of_sample(card_cfg: dict | None = None) -> dict:
    """Онлайн-MAE вне выборки: OOF-прогнозы ансамбля LOBO на реальных точках test.

    Финальные модели обучены на labels train + test, поэтому replay дня test для них — «в выборке».
    Честная цифра — прогнозы моделей, не видевших борт (LOBO), в те же моменты T: признаки потока
    совпадают с офлайновыми (``tests/ml/test_online_parity.py``), значит, это и есть онлайн-прогноз.
    """
    from ml_core.inference import base_of as _base
    from src.ml.dataset import load_pool

    cfg = card_cfg or json.loads((ROOT / "models" / "feature_config.json").read_text(encoding="utf-8"))
    on, ss = cfg["models"]["m_online"], cfg["models"]["m_sched"]
    bl = cfg.get("blend", {})
    ws, wm = float(bl.get("w_sched", 0.0)), float(bl.get("w_mlp", 0.0))
    t3 = ROOT / "cache" / "t3"
    pr = load_pool("reconstructed")
    y, cur = pr["target_delay_s"].to_numpy(), pr["cur_dev_s"].to_numpy()
    base = _base(cur, on["base_mode"])
    cat = np.load(t3 / f"oof_m_online_{on['base_mode']}.npz", allow_pickle=True)[f"it{on['iterations']}"]
    sch = np.load(t3 / f"oof_m_sched_{ss['base_mode']}.npz", allow_pickle=True)[f"it{ss['iterations']}"]
    mlp = base + np.load(t3 / f"oof_mlp_{on['base_mode']}.npz", allow_pickle=True)["d_mlp"] if wm else 0.0
    pred = np.clip((1 - ws - wm) * cat + ws * sch + wm * mlp, -400, 700)
    m = ((pr["split"] == "test") & (pr["tr_id"] < 9_000_000)).to_numpy()
    late, warned = y[m] > 120.0, pred[m] > 120.0
    return {"n_points": int(m.sum()), "online_mae_model_s": float(np.abs(pred[m] - y[m]).mean()),
            "online_mae_baseline_s": float(np.abs(_base(cur[m]) - y[m]).mean()),
            "online_mae_zero_s": float(np.abs(y[m]).mean()),
            # ранние предупреждения для незнакомого борта: опоздание > 2 мин предсказано заранее
            "late_events": int(late.sum()),
            "late_warned_share": float(warned[late].mean()) if late.any() else float("nan"),
            "warning_precision": float(late[warned].mean()) if warned.any() else float("nan")}


def render(m300: dict, m60: dict, oos: dict | None = None) -> str:
    def row(name, key, fmt="{:.1f}"):
        return f"| {name} | {fmt.format(m300[key])} | {fmt.format(m60[key])} |"

    causes = sorted(set(m300["causes_pct"]) | set(m60["causes_pct"]))
    lines = [
        "# Онлайн-replay дня test: горизонт и онлайн-MAE",
        "",
        f"Реальные борта test ({m60['buses']}) проигрываются через `OnlineVehicle` (фиксы по времени), на каждом тике: "
        "`target_at(T)` → `features_at(T)` → предиктор ml-core (локально). Факт — `test/schedule.csv` "
        "(только для оценки). Бейзлайн — «задержка = восстановленное `cur_dev`» (NaN → 0).",
        "",
        "| Метрика | тик 5 мин | тик 60 с |",
        "|---|---|---|",
        row("Тиков (борт × момент)", "ticks_total", "{:d}"),
        row("Прогнозов построено", "forecasts_total", "{:d}"),
        row("Покрытие (доля тиков с прогнозом)", "coverage", "{:.3f}"),
        row("Доля прогнозов с lead ∈ [600, 900] с", "share_lead_in_window", "{:.3f}"),
        row("Сверено с фактом", "resolved_total", "{:d}"),
        row("**Онлайн-MAE модели, с**", "online_mae_model_s"),
        row("Онлайн-MAE бейзлайна `cur_dev` (восст.), с", "online_mae_baseline_s"),
        row("Онлайн-MAE «задержка = 0», с", "online_mae_zero_s"),
        row("Факт внутри q10–q90", "interval_coverage", "{:.3f}"),
        row("Прогнозов, выданных ДО фактического прибытия", "share_issued_before_actual_arrival", "{:.3f}"),
        row("Минимальный фактический запас до прибытия, с", "actual_lead_min_s", "{:.0f}"),
        row("Медианный фактический запас до прибытия, с", "actual_lead_p50_s", "{:.0f}"),
        row("Фактических опозданий > 2 мин", "late_events", "{:d}"),
        row("Из них модель заранее предсказала > 2 мин", "late_warned_share", "{:.3f}"),
        row("Точность предупреждений (прогноз > 2 мин → опоздание)", "warning_precision", "{:.3f}"),
        row("Средняя P(опоздание): у опоздавших / у вовремя", "late_p_late_mean", "{:.2f}"),
        row("Время на борт (признаки + доля батча), p50, мс", "per_bus_ms_p50", "{:.2f}"),
        row("Время на борт, p99, мс", "per_bus_ms_p99", "{:.2f}"),
        "",
        "## Причины (доля прогнозов, %)",
        "",
        "| Причина | тик 5 мин | тик 60 с |",
        "|---|---|---|",
    ] + [f"| `{c}` | {m300['causes_pct'].get(c, 0.0)} | {m60['causes_pct'].get(c, 0.0)} |" for c in causes] + [
        "",
        "Покрытие < 1: в часы без остановки в окне (T+10, T+15] (ночь, отстой на конечной) прогноз по правилу "
        "не строится — это требование критерия 2, а не отказ системы.",
    ]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--buses", type=int, default=0, help="сколько бортов (0 — все)")
    ap.add_argument("--out", default="reports/online_eval.md")
    ap.add_argument("--no-card", action="store_true")
    ap.add_argument("--from-card", action="store_true", help="не гонять replay: взять метрики из model_card.json")
    args = ap.parse_args(argv)
    card_path = ROOT / "models" / "model_card.json"
    labels = pd.read_csv(DATA / "labels" / "labels_test.csv")
    buses = sorted(int(x) for x in labels.tr_id.unique())
    if args.buses:
        buses = buses[:args.buses]
    m = {}
    if args.from_card:
        oe = json.loads(card_path.read_text(encoding="utf-8"))["online_eval"]
        m = {300: oe["tick_300s"], 60: oe["tick_60s"]}
    else:
        pred = Predictor()
        pred.load()
        for tick in (300, 60):
            t0 = time.time()
            m[tick] = summarize(run_replay(buses, tick, pred))
            print(f"tick {tick}s: {time.time() - t0:.0f} s, MAE model {m[tick]['online_mae_model_s']:.1f} "
                  f"vs baseline {m[tick]['online_mae_baseline_s']:.1f}, lead ok {m[tick]['share_lead_in_window']:.3f}")
    oos = out_of_sample()
    print(f"out of sample (LOBO, test points): {oos}")
    out = ROOT / args.out
    out.parent.mkdir(exist_ok=True)
    out.write_text(render(m[300], m[60], oos), encoding="utf-8")
    if not args.no_card:
        card = json.loads(card_path.read_text(encoding="utf-8"))
        card["online_eval"] = {"tick_300s": m[300], "tick_60s": m[60], "out_of_sample_lobo": oos}
        card_path.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
