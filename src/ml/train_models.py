"""Обучение моделей ML-T3: m_ds, m_online (+ q10/q90), m_sched; LOBO-выбор итераций, FWD, official.

Запуск из корня репозитория: ``.venv312/Scripts/python.exe -m src.ml.train_models``.

Правила (анти-утечка): итерации и база остатка выбираются только по LOBO; test и validate не
участвуют в выборе (official печатается только для сравнения с LB; вариант сабмита с/без TOD — тоже по LOBO). Финальные модели — среднее 5 сидов (``sum_models``), обучены на train + test labels.

Промежуточные результаты LOBO кешируются в ``cache/t3/`` — перезапуск не пересчитывает готовое.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor, sum_models

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)  # CatBoost на Windows: только относительные (ASCII) пути

from features import FEATURES_VERSION  # noqa: E402
from features.io import load_schedule  # noqa: E402
from ml_core.inference import (CAUSE_GROUPS, base_of, calibrate_interval_scale, compute_norms,  # noqa: E402
                               order_quantiles, to_delay)
from src.ml.cv import add_bus, check_mapping, fwd_split, lobo_folds, official_split, real_buses  # noqa: E402
from src.ml.dataset import (M_DS_FEATURES, M_DS_NOTOD_FEATURES, M_ONLINE_FEATURES, M_SCHED_FEATURES,  # noqa: E402
                            load_points, load_pool)
from src.submission_journal import git_hash_short  # noqa: E402

CB_PARAMS = dict(learning_rate=0.04, depth=6, l2_leaf_reg=5, loss_function="MAE", verbose=0,
                 allow_writing_files=False, thread_count=-1,
                 border_count=64)  # 64 вместо 254: в 2.3 раза быстрее на слабом ноутбуке, official MAE не хуже
ITER_GRID = [400, 600, 800, 1200]
SEEDS = [0, 1, 2, 3, 4]
Q_ITERS = 500
SCHED_ITERS = 600
T3_CACHE = ROOT / "cache" / "t3"
MODELS = Path("models")


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def fit(X: pd.DataFrame, z: np.ndarray, iters: int, seed: int, loss: str = "MAE") -> CatBoostRegressor:
    """Один CatBoost с фиксированными параметрами (без early stopping)."""
    m = CatBoostRegressor(**{**CB_PARAMS, "loss_function": loss}, iterations=iters, random_seed=seed)
    m.fit(X, z)
    return m


def mae(a, b) -> float:
    return float(np.mean(np.abs(np.asarray(a, dtype=float) - np.asarray(b, dtype=float))))


def lobo_oof(name: str, pool: pd.DataFrame, feats: list[str], base_mode: str, iters: list[int],
             folds, loss: str = "MAE") -> dict[int, np.ndarray]:
    """OOF-прогноз задержки на реальных точках для каждого числа итераций (одна модель на фолд, сид 0).

    Модели с меньшим числом итераций — префиксы (``ntree_end``): то же, что обучить заново.
    """
    T3_CACHE.mkdir(parents=True, exist_ok=True)
    path = T3_CACHE / f"oof_{name}.npz"
    key = json.dumps([feats, base_mode, iters, loss, CB_PARAMS, len(pool)], sort_keys=True)
    if path.exists():
        d = np.load(path, allow_pickle=True)
        if str(d["key"]) == key:
            return {int(k): d[f"it{k}"] for k in iters}
    y = pool["target_delay_s"].to_numpy()
    cur = pool["cur_dev_s"].to_numpy()
    z = y - base_of(cur, base_mode)
    out = {k: np.full(len(pool), np.nan) for k in iters}
    t0 = time.time()
    for tr, te in folds:
        m = fit(pool.iloc[tr][feats], z[tr], max(iters), 0, loss)
        for k in iters:
            out[k][te] = to_delay(cur[te], m.predict(pool.iloc[te][feats], ntree_end=k), base_mode)
    np.savez(path, key=key, **{f"it{k}": v for k, v in out.items()})
    log(f"LOBO {name}: {time.time() - t0:.0f} s")
    return out


def eval_split(pool, feats, base_mode, iters, tr, te, seeds=(0,), loss="MAE") -> np.ndarray:
    """Прогноз задержки на ``te`` моделью (среднее сидов), обученной на ``tr``."""
    y = pool["target_delay_s"].to_numpy()
    cur = pool["cur_dev_s"].to_numpy()
    z = y - base_of(cur, base_mode)
    deltas = [fit(pool.iloc[tr][feats], z[tr], iters, s, loss).predict(pool.iloc[te][feats]) for s in seeds]
    return to_delay(cur[te], np.mean(deltas, axis=0), base_mode)


def train_final(pool, feats, base_mode, iters, loss="MAE", seeds=SEEDS) -> tuple[CatBoostRegressor, list]:
    """Финальная модель: ``sum_models`` 5 сидов с весами 0.2, обучена на всём пуле (train + test labels)."""
    y = pool["target_delay_s"].to_numpy()
    z = y - base_of(pool["cur_dev_s"].to_numpy(), base_mode)
    ms = [fit(pool[feats], z, iters, s, loss) for s in seeds]
    return sum_models(ms, weights=[1.0 / len(ms)] * len(ms)), ms


def save_model(model: CatBoostRegressor, name: str) -> str:
    MODELS.mkdir(exist_ok=True)
    path = (MODELS / f"{name}.cbm").as_posix()
    model.save_model(path)
    return path


def main() -> None:
    t_start = time.time()
    real = real_buses(load_points("test"))
    po = add_bus(load_pool("official"), real)
    pr = add_bus(load_pool("reconstructed"), real)
    mapping = check_mapping(po, real, load_schedule("data/train/schedule.csv"))
    log(f"mapping ok: {mapping}")
    folds = lobo_folds(po)
    for tr, te in folds:  # анти-утечка: ни точки отложенного борта, ни его копий в train
        assert not set(po.bus.iloc[tr]) & set(po.bus.iloc[te])
    real_mask = po["is_real"].to_numpy()
    y = po["target_delay_s"].to_numpy()
    yr = y[real_mask]
    card: dict = {"created_at": datetime.now().isoformat(timespec="seconds"), "git_hash": git_hash_short(),
                  "features_version": FEATURES_VERSION, "cb_params": CB_PARAMS, "mapping_checks": mapping,
                  "n_points": {"pool": len(po), "pool_real": int(real_mask.sum()), "train": int((po.split == "train").sum()),
                               "test": int((po.split == "test").sum())}}

    # ---------- бейзлайны ----------
    cur_off, cur_rec = po["cur_dev_s"].to_numpy(), pr["cur_dev_s"].to_numpy()
    tr_o, te_o = official_split(po)
    tr_f, te_f = fwd_split(po)
    card["baselines"] = {
        "lobo_cur_dev_official": mae(yr, cur_off[real_mask]),
        "lobo_cur_dev_reconstructed": mae(yr, base_of(cur_rec[real_mask])),
        "lobo_zero": mae(yr, 0.0),
        "official_cur_dev": mae(y[te_o], cur_off[te_o]),
        "fwd_cur_dev": mae(y[te_f], cur_off[te_f]),
        "fwd_cur_dev_reconstructed": mae(y[te_f], base_of(cur_rec[te_f])),
    }
    log(f"baselines: { {k: round(v, 1) for k, v in card['baselines'].items()} }")

    # ---------- m_ds: итерации по LOBO, абляция TOD ----------
    oof = lobo_oof("m_ds", po, M_DS_FEATURES, "cur_dev", ITER_GRID, folds)
    by_it = {k: mae(yr, v[real_mask]) for k, v in oof.items()}
    it_ds = min(by_it, key=by_it.get)
    oof_nt = lobo_oof("m_ds_notod", po, M_DS_NOTOD_FEATURES, "cur_dev", ITER_GRID, folds)
    by_it_nt = {k: mae(yr, v[real_mask]) for k, v in oof_nt.items()}
    log(f"m_ds LOBO by iters {by_it} -> {it_ds}; no TOD {by_it_nt}")
    off_tod = mae(y[te_o], eval_split(po, M_DS_FEATURES, "cur_dev", it_ds, tr_o, te_o, SEEDS))
    off_nt = mae(y[te_o], eval_split(po, M_DS_NOTOD_FEATURES, "cur_dev", it_ds, tr_o, te_o, SEEDS))
    fwd_ds = mae(y[te_f], eval_split(po, M_DS_FEATURES, "cur_dev", it_ds, tr_f, te_f))
    # вариант с TOD / без — по LOBO (official печатается только для сравнения; на 26.09 оба выбирают tod)
    variant = "tod" if by_it[it_ds] <= by_it_nt[it_ds] else "notod"
    per_bus = pd.Series(np.abs(oof[it_ds] - y)[real_mask]).groupby(po.bus.to_numpy()[real_mask]).mean().round(1)
    card["m_ds"] = {"iterations": it_ds, "lobo_by_iter": by_it, "lobo_mae": by_it[it_ds],
                    "lobo_by_iter_notod": by_it_nt, "lobo_mae_notod": by_it_nt[it_ds],
                    "official_mae_tod": off_tod, "official_mae_notod": off_nt, "submission_variant": variant,
                    "official_mae": off_tod if variant == "tod" else off_nt, "fwd_mae": fwd_ds,
                    "lobo_mae_per_bus": {str(k): float(v) for k, v in per_bus.items()}}
    log(f"m_ds: LOBO {by_it[it_ds]:.2f} (no TOD {by_it_nt[it_ds]:.2f}), official TOD {off_tod:.2f} / "
        f"no TOD {off_nt:.2f} -> {variant}, FWD {fwd_ds:.2f}")

    # ---------- m_online: база остатка и итерации по LOBO ----------
    res = {}
    for bm in ("cur_dev", "zero"):
        o = lobo_oof(f"m_online_{bm}", pr, M_ONLINE_FEATURES, bm, ITER_GRID, folds)
        res[bm] = (o, {k: mae(yr, v[real_mask]) for k, v in o.items()})
    base_on, it_on = min(((bm, k) for bm in res for k in ITER_GRID), key=lambda x: res[x[0]][1][x[1]])
    oof_on = res[base_on][0][it_on]
    lobo_on = res[base_on][1][it_on]
    log(f"m_online LOBO: cur_dev {res['cur_dev'][1]} | zero {res['zero'][1]} -> base={base_on}, it={it_on}")
    q10 = lobo_oof(f"m_online_q10_{base_on}", pr, M_ONLINE_FEATURES, base_on, [Q_ITERS], folds, "Quantile:alpha=0.1")[Q_ITERS]
    q90 = lobo_oof(f"m_online_q90_{base_on}", pr, M_ONLINE_FEATURES, base_on, [Q_ITERS], folds, "Quantile:alpha=0.9")[Q_ITERS]
    lo_, hi_ = order_quantiles(oof_on, q10, q90)
    cover = float(np.mean((yr >= lo_[real_mask]) & (yr <= hi_[real_mask])))
    fwd_on = mae(y[te_f], eval_split(pr, M_ONLINE_FEATURES, base_on, it_on, tr_f, te_f))
    off_on = mae(y[te_o], eval_split(pr, M_ONLINE_FEATURES, base_on, it_on, tr_o, te_o))
    card["m_online"] = {"base_mode": base_on, "iterations": it_on, "lobo_mae": lobo_on,
                        "lobo_by_iter": {bm: r[1] for bm, r in res.items()}, "fwd_mae": fwd_on, "official_mae": off_on,
                        "interval_q10_q90_coverage_lobo": cover,
                        "interval_width_median_s": float(np.median((hi_ - lo_)[real_mask]))}
    log(f"m_online: LOBO {lobo_on:.2f}, FWD {fwd_on:.2f}, official {off_on:.2f}, q10–q90 coverage {cover:.2f}")

    # ---------- m_sched: fallback без телеметрии ----------
    sres = {}
    for bm in ("cur_dev", "zero"):
        o = lobo_oof(f"m_sched_{bm}", pr, M_SCHED_FEATURES, bm, [SCHED_ITERS], folds)[SCHED_ITERS]
        sres[bm] = (o, mae(yr, o[real_mask]))
    base_sc = min(sres, key=lambda b: sres[b][1])
    card["m_sched"] = {"base_mode": base_sc, "iterations": SCHED_ITERS, "lobo_mae": sres[base_sc][1],
                       "lobo_mae_by_base": {b: v[1] for b, v in sres.items()},
                       "fwd_mae": mae(y[te_f], eval_split(pr, M_SCHED_FEATURES, base_sc, SCHED_ITERS, tr_f, te_f))}
    log(f"m_sched: LOBO {sres[base_sc][1]:.2f} (base {base_sc})")

    # ---------- финальные модели (train + test labels, 5 сидов) ----------
    ds_feats = M_DS_FEATURES if variant == "tod" else M_DS_NOTOD_FEATURES
    specs = {
        "m_ds": (po, ds_feats, "cur_dev", it_ds, "MAE"),
        "m_ds_notod": (po, M_DS_NOTOD_FEATURES, "cur_dev", it_ds, "MAE"),
        "m_ds_tod": (po, M_DS_FEATURES, "cur_dev", it_ds, "MAE"),
        "m_online": (pr, M_ONLINE_FEATURES, base_on, it_on, "MAE"),
        "m_online_q10": (pr, M_ONLINE_FEATURES, base_on, Q_ITERS, "Quantile:alpha=0.1"),
        "m_online_q90": (pr, M_ONLINE_FEATURES, base_on, Q_ITERS, "Quantile:alpha=0.9"),
        "m_sched": (pr, M_SCHED_FEATURES, base_sc, SCHED_ITERS, "MAE"),
    }
    models_cfg = {}
    for name, (pool, feats, bm, iters, loss) in specs.items():
        if name == "m_ds_tod" and variant == "tod" or name == "m_ds_notod" and variant == "notod":
            continue  # совпадает с m_ds
        t0 = time.time()
        final, seeds_models = train_final(pool, feats, bm, iters, loss)
        models_cfg[name] = {"file": save_model(final, name), "features": feats, "base_mode": bm, "iterations": iters,
                            "loss": loss, "seeds": SEEDS,
                            "cur_dev_source": "official" if pool is po else "reconstructed"}
        if name == "m_ds":  # запасной сабмит: 3 сида вместо 5
            m3 = sum_models(seeds_models[:3], weights=[1 / 3] * 3)
            models_cfg["m_ds_3seeds"] = {**models_cfg["m_ds"], "file": save_model(m3, "m_ds_3seeds"), "seeds": SEEDS[:3]}
        log(f"final {name}: {time.time() - t0:.0f} s")

    # ---------- нормы для причин ----------
    norms = {
        "m_online": compute_norms(pr[M_ONLINE_FEATURES].to_numpy(float), M_ONLINE_FEATURES, y),
        "m_ds": compute_norms(po[ds_feats].to_numpy(float), ds_feats, y),
    }
    model_version = f"m_online-v1-{git_hash_short()}"
    config = {"features_version": FEATURES_VERSION, "model_version": model_version, "models": models_cfg,
              "norms": norms, "cause_groups": CAUSE_GROUPS, "clip_s": [-400.0, 700.0], "late_threshold_s": 120.0,
              "blend": {"members": ["catboost"], "w_mlp": 0.0}}
    (MODELS / "feature_config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    card["model_version"] = model_version
    card["train_minutes"] = round((time.time() - t_start) / 60, 1)
    (MODELS / "model_card.json").write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"done in {card['train_minutes']} min; model_version={model_version}")
    calibrate_interval()


def calibrate_interval() -> float:
    """Калибрует ширину q10–q90 по OOF LOBO (цель — 80 % фактов внутри) и пишет ``interval_scale``."""
    cfg_path, card_path = MODELS / "feature_config.json", MODELS / "model_card.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    card = json.loads(card_path.read_text(encoding="utf-8"))
    spec = cfg["models"]["m_online"]
    bm, it = spec["base_mode"], spec["iterations"]
    pr = add_bus(load_pool("reconstructed"), real_buses(load_points("test")))
    real = pr["is_real"].to_numpy()
    y = pr["target_delay_s"].to_numpy()[real]
    pred = np.load(T3_CACHE / f"oof_m_online_{bm}.npz", allow_pickle=True)[f"it{it}"][real]
    q10 = np.load(T3_CACHE / f"oof_m_online_q10_{bm}.npz", allow_pickle=True)[f"it{Q_ITERS}"][real]
    q90 = np.load(T3_CACHE / f"oof_m_online_q90_{bm}.npz", allow_pickle=True)[f"it{Q_ITERS}"][real]
    scale = calibrate_interval_scale(y, pred, q10, q90, 0.8)
    lo, hi = order_quantiles(pred, q10, q90, scale)
    cfg["interval_scale"] = scale
    card["m_online"]["interval_scale"] = scale
    card["m_online"]["interval_q10_q90_coverage_lobo_calibrated"] = float(np.mean((y >= lo) & (y <= hi)))
    card["m_online"]["interval_width_median_calibrated_s"] = float(np.median(hi - lo))
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    card_path.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"interval scale {scale}: coverage {card['m_online']['interval_q10_q90_coverage_lobo_calibrated']:.3f}")
    return scale


if __name__ == "__main__":
    if "--calibrate-only" in sys.argv:
        calibrate_interval()
    else:
        main()
