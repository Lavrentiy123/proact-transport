"""PyTorch MLP — член ансамбля m_online (требование стека), ONNX-экспорт, LOBO-вес бленда.

Запуск из корня: ``.venv312/Scripts/python.exe -m src.ml.torch_mlp`` (после ``src.ml.train_models``).

- Вход — признаки m_online; NaN → медиана train + индикатор пропуска (доля NaN > 5 %); стандартизация.
- ``Linear(d→64) → ReLU → Dropout(0.1) → Linear(64→32) → ReLU → Linear(32→1)``, target Δ (та же база,
  что у m_online), L1, Adam(lr=1e-3, wd=1e-4), batch 256, ровно 60 эпох (без early stopping), сиды 0–4, CPU.
- Веса бленда прогнозов задержки ``ŷ = w_cat·cat + w_sched·sched + w_mlp·mlp`` — по LOBO (те же 13 фолдов):
  ``w_mlp ∈ {0, 0.1, …, 0.5}`` (правило спецификации: при лучшем 0 берём 0.1, если хуже не более 0.5 с),
  ``w_sched ∈ {0, 0.25, 0.5, 0.75}`` — m_sched (7 признаков расписания) на LOBO оказался не хуже m_online.
- Финальный MLP — среднее 5 сидов в одном ONNX-графе ``models/m_online_mlp.onnx``; препроцессинг и вес —
  в ``models/feature_config.json``, в ml-core — onnxruntime.
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import torch
from torch import nn

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from ml_core.inference import (base_of, calibrate_interval_scale, mlp_fit_prep, mlp_transform,  # noqa: E402
                               order_quantiles, to_delay)
from src.ml.cv import add_bus, lobo_folds, real_buses  # noqa: E402
from src.ml.dataset import load_points, load_pool  # noqa: E402
from src.submission_journal import git_hash_short  # noqa: E402

EPOCHS, BATCH, LR, WD = 60, 256, 1e-3, 1e-4
SEEDS = [0, 1, 2, 3, 4]
W_GRID = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
W_SCHED_GRID = [0.0, 0.25, 0.5, 0.75]  # m_sched как член ансамбля: на LOBO он не хуже m_online
TARGET_SCALE = 100.0  # L1 масштабно-эквивариантна: учим Δ/100, выход модели умножается обратно
ONNX_PATH = Path("models/m_online_mlp.onnx")
torch.set_num_threads(4)


class MLP(nn.Module):
    """Малая сеть для остатка Δ; выход в секундах."""

    def __init__(self, d_in: int):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(d_in, 64), nn.ReLU(), nn.Dropout(0.1), nn.Linear(64, 32), nn.ReLU(),
                                 nn.Linear(32, 1))
        self.register_buffer("scale", torch.tensor(TARGET_SCALE))

    def forward(self, x):
        return self.net(x) * self.scale


class SeedEnsemble(nn.Module):
    """Среднее нескольких MLP — один ONNX-граф для инференса."""

    def __init__(self, members: list[MLP]):
        super().__init__()
        self.members = nn.ModuleList(members)

    def forward(self, x):
        return torch.stack([m(x) for m in self.members], dim=0).mean(dim=0)


def train_one(Z: np.ndarray, z: np.ndarray, seed: int) -> MLP:
    """Ровно 60 эпох Adam с L1 на ``Δ / 100``."""
    torch.manual_seed(seed)
    gen = torch.Generator().manual_seed(seed)
    model = MLP(Z.shape[1])
    opt = torch.optim.Adam(model.parameters(), lr=LR, weight_decay=WD)
    Xt, yt = torch.from_numpy(Z), torch.from_numpy((z / TARGET_SCALE).astype(np.float32)).reshape(-1, 1)
    loss_fn = nn.L1Loss()
    model.train()
    for _ in range(EPOCHS):
        perm = torch.randperm(len(Xt), generator=gen)
        for b in range(0, len(Xt), BATCH):
            idx = perm[b:b + BATCH]
            opt.zero_grad()
            loss = loss_fn(model.net(Xt[idx]), yt[idx])
            loss.backward()
            opt.step()
    return model.eval()


def predict_members(members: list[MLP], Z: np.ndarray) -> np.ndarray:
    with torch.no_grad():
        return SeedEnsemble(members).eval()(torch.from_numpy(Z)).numpy().reshape(-1).astype(np.float64)


def export_onnx(members: list[MLP], d_in: int) -> bytes:
    """ONNX (opset 17, динамический batch) среднего сидов; модель в ``eval()`` — Dropout выключен."""
    ens = SeedEnsemble(members).eval()
    buf = io.BytesIO()
    torch.onnx.export(ens, (torch.zeros(2, d_in),), buf, opset_version=17, input_names=["x"], output_names=["y"],
                      dynamic_axes={"x": {0: "batch"}, "y": {0: "batch"}}, dynamo=False)
    return buf.getvalue()


def main() -> None:
    t0 = time.time()
    cfg_path, card_path = Path("models/feature_config.json"), Path("models/model_card.json")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    card = json.loads(card_path.read_text(encoding="utf-8"))
    spec = cfg["models"]["m_online"]
    feats, bm, it = spec["features"], spec["base_mode"], spec["iterations"]

    pr = add_bus(load_pool("reconstructed"), real_buses(load_points("test")))
    folds = lobo_folds(pr)
    real = pr["is_real"].to_numpy()
    y = pr["target_delay_s"].to_numpy()
    cur = pr["cur_dev_s"].to_numpy()
    base = base_of(cur, bm)
    z = y - base
    X = pr[feats].to_numpy(np.float64)

    # OOF CatBoost из кеша ML-T3 (прогноз задержки → остаток; клип почти не срабатывает)
    oof_cat_delay = np.load(ROOT / "cache" / "t3" / f"oof_m_online_{bm}.npz", allow_pickle=True)[f"it{it}"]
    n_clipped = int(np.sum(real & ((oof_cat_delay <= -400) | (oof_cat_delay >= 700))))
    d_cat = oof_cat_delay - base

    oof_path = ROOT / "cache" / "t3" / f"oof_mlp_{bm}.npz"
    key = json.dumps([feats, bm, EPOCHS, BATCH, LR, WD, SEEDS, TARGET_SCALE, len(pr)])
    d_mlp = None
    if oof_path.exists():
        d = np.load(oof_path, allow_pickle=True)
        d_mlp = d["d_mlp"] if str(d["key"]) == key else None
    if d_mlp is None:
        d_mlp = np.full(len(pr), np.nan)
        for tr, te in folds:
            prep = mlp_fit_prep(X[tr], feats)
            Ztr, Zte = mlp_transform(X[tr], prep), mlp_transform(X[te], prep)
            d_mlp[te] = predict_members([train_one(Ztr, z[tr], s) for s in SEEDS], Zte)
        np.savez(oof_path, key=key, d_mlp=d_mlp)
    print(f"MLP LOBO done in {time.time() - t0:.0f} s", flush=True)

    ss = cfg["models"]["m_sched"]
    oof_sched = np.load(ROOT / "cache" / "t3" / f"oof_m_sched_{ss['base_mode']}.npz", allow_pickle=True)[f"it{ss['iterations']}"]
    d_cat_delay, d_mlp_delay = base + d_cat, base + d_mlp

    def mae_w(ws, wm):
        p = np.clip((1 - ws - wm) * d_cat_delay[real] + ws * oof_sched[real] + wm * d_mlp_delay[real], -400, 700)
        return float(np.mean(np.abs(p - y[real])))

    grid = {(ws, wm): mae_w(ws, wm) for ws in W_SCHED_GRID for wm in W_GRID if ws + wm <= 1.0 + 1e-9}
    best_ws, best_wm = min(grid, key=grid.get)
    ws, w = best_ws, best_wm
    note = "веса выбраны по минимуму LOBO"
    if best_wm == 0.0:
        if grid[(ws, 0.1)] - grid[(ws, 0.0)] <= 0.5:
            w, note = 0.1, "лучший w_mlp = 0; взят w_mlp = 0.1 (ухудшение LOBO ≤ 0.5 с)"
        else:
            note = "лучший w_mlp = 0, а 0.1 хуже > 0.5 с: MLP загружен и обслуживается, но в бленд не вошёл"
    by_w = {wm: grid[(ws, wm)] for wm in W_GRID if (ws, wm) in grid}
    lobo_mlp = float(np.mean(np.abs(to_delay(cur[real], d_mlp[real], bm) - y[real])))
    print(f"LOBO: cat {grid[(0.0, 0.0)]:.2f}, sched-blend {grid[(ws, 0.0)]:.2f}, mlp alone {lobo_mlp:.2f}, "
          f"best (w_sched={best_ws}, w_mlp={best_wm}) {grid[(best_ws, best_wm)]:.2f} -> w_sched={ws}, w_mlp={w} ({note})",
          flush=True)

    # ширина q10–q90 перекалибровывается под прогноз ансамбля (OOF LOBO, цель 80 %)
    q_it = cfg["models"]["m_online_q10"]["iterations"]
    q10 = np.load(ROOT / "cache" / "t3" / f"oof_m_online_q10_{bm}.npz", allow_pickle=True)[f"it{q_it}"]
    q90 = np.load(ROOT / "cache" / "t3" / f"oof_m_online_q90_{bm}.npz", allow_pickle=True)[f"it{q_it}"]
    blend_oof = np.clip((1 - ws - w) * d_cat_delay + ws * oof_sched + w * d_mlp_delay, -400, 700)
    scale = calibrate_interval_scale(y[real], blend_oof[real], q10[real], q90[real], 0.8)
    lo, hi = order_quantiles(blend_oof[real], q10[real], q90[real], scale)
    cover = float(np.mean((y[real] >= lo) & (y[real] <= hi)))
    print(f"interval scale for blend: {scale} (coverage {cover:.3f})", flush=True)

    # финальный MLP на всём пуле
    prep = mlp_fit_prep(X, feats)
    members = [train_one(mlp_transform(X, prep), z, s) for s in SEEDS]
    ONNX_PATH.write_bytes(export_onnx(members, mlp_transform(X[:1], prep).shape[1]))
    cfg["blend"] = {"members": ["catboost", "catboost_sched", "torch_mlp_onnx"], "w_mlp": w, "w_sched": ws,
                    "mlp": {**prep, "file": ONNX_PATH.as_posix(), "base_mode": bm, "seeds": SEEDS, "epochs": EPOCHS}}
    cfg["interval_scale"] = scale
    # версия потока: v2 = ансамбль (CatBoost-sched + PyTorch/ONNX), хеш — текущий коммит
    cfg["model_version"] = card["model_version"] = f"m_online-v2-ens-{git_hash_short()}"
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    card["m_online"]["interval_scale"] = scale
    card["m_online"]["interval_q10_q90_coverage_lobo_calibrated"] = cover
    card["m_online"]["interval_width_median_calibrated_s"] = float(np.median(hi - lo))
    card["m_online_mlp"] = {"lobo_mae_mlp": lobo_mlp, "lobo_mae_cat": grid[(0.0, 0.0)],
                            "lobo_mae_cat_sched": grid[(ws, 0.0)], "lobo_by_w_mlp": {str(k): v for k, v in by_w.items()},
                            "lobo_grid": {f"sched={a}|mlp={b}": v for (a, b), v in grid.items()},
                            "w_mlp": w, "w_sched": ws, "lobo_mae_blend": grid[(ws, w)], "note": note,
                            "oof_cat_clipped_rows": n_clipped,
                            "arch": "Linear(d,64)-ReLU-Dropout(0.1)-Linear(64,32)-ReLU-Linear(32,1)",
                            "epochs": EPOCHS, "seeds": len(SEEDS), "minutes": round((time.time() - t0) / 60, 1)}
    card["ensemble_weights"] = {"catboost": round(1 - w - ws, 3), "catboost_sched": ws, "torch_mlp_onnx": w}
    card_path.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"done in {(time.time() - t0) / 60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
