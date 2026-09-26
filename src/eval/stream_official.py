"""Official split для моделей потока: обучение на train labels → точки test (как LB: тот же день, те же борта).

Запуск из корня: ``.venv312/Scripts/python.exe -m src.eval.stream_official`` → раздел ``stream_submission`` в
``models/model_card.json``. Признаки — восстановленные детектором (как на потоке), параметры членов и веса
бленда — из ``models/feature_config.json`` (выбраны по LOBO). Скрипт только оценивает: по его цифрам выбирается
вариант сабмита из потока (ансамбль или один CatBoost), модели сервиса он не меняет.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml_core.inference import base_of, mlp_fit_prep, mlp_transform  # noqa: E402
from src.ml.cv import add_bus, official_split, real_buses  # noqa: E402
from src.ml.dataset import load_points, load_pool  # noqa: E402
from src.ml.torch_mlp import SEEDS as MLP_SEEDS, predict_members, train_one  # noqa: E402
from src.ml.train_models import SEEDS, eval_split  # noqa: E402

LB_MAE_ZERO, LB_MAE_TARGET = 108.1, 60.0  # шкала скора validate (docs/DEEP_ANALYSIS_RESULT.md, I.3)


def score_est(mae: float) -> float:
    """Оценка скора платформы по MAE: ``(108.1 − MAE) / (108.1 − 60)``."""
    return (LB_MAE_ZERO - mae) / (LB_MAE_ZERO - LB_MAE_TARGET)


def main() -> int:
    cfg = json.loads((ROOT / "models" / "feature_config.json").read_text(encoding="utf-8"))
    on, ss, bl = cfg["models"]["m_online"], cfg["models"]["m_sched"], cfg["blend"]
    pr = add_bus(load_pool("reconstructed"), real_buses(load_points("test")))
    tr, te = official_split(pr)
    y, cur = pr["target_delay_s"].to_numpy(), pr["cur_dev_s"].to_numpy()
    cat = eval_split(pr, on["features"], on["base_mode"], on["iterations"], tr, te, SEEDS)
    sch = eval_split(pr, ss["features"], ss["base_mode"], ss["iterations"], tr, te, SEEDS)
    X, base = pr[on["features"]].to_numpy(np.float64), base_of(cur, on["base_mode"])
    prep = mlp_fit_prep(X[tr], on["features"])
    d = predict_members([train_one(mlp_transform(X[tr], prep), (y - base)[tr], s) for s in MLP_SEEDS],
                        mlp_transform(X[te], prep))
    mlp = np.clip(base[te] + d, -400, 700)
    ws, wm = float(bl.get("w_sched", 0.0)), float(bl.get("w_mlp", 0.0))
    blend = np.clip((1 - ws - wm) * cat + ws * sch + wm * mlp, -400, 700)
    mae = {k: float(np.mean(np.abs(p - y[te]))) for k, p in
           {"cat": cat, "sched": sch, "mlp": mlp, "blend": blend}.items()}
    out = {"n_points": int(len(te)), "official_mae": mae, "score_est": {k: round(score_est(v), 3) for k, v in mae.items()},
           "weights": {"w_cat": round(1 - ws - wm, 3), "w_sched": ws, "w_mlp": wm}}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    card_path = ROOT / "models" / "model_card.json"
    card = json.loads(card_path.read_text(encoding="utf-8"))
    card["stream_submission"] = out
    card_path.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
