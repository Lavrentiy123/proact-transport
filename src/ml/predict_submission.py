"""Сабмит по validate: ``python -m src.ml.predict_submission --model m_ds``.

Признаки validate строятся по ``validate/traffic.csv`` и ``validate/schedule_plan.csv`` (только план)
с официальной подсказкой ``cur_dev_s``. Файл пишется в ``submissions/sub_<ts>_<tag>.csv``, проходит
валидатор и попадает в журнал ``submissions/journal.csv``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from ml_core.inference import to_delay  # noqa: E402
from src.ml.dataset import load_features  # noqa: E402
from src.submission_journal import save_submission  # noqa: E402
from src.validate_submission import validate  # noqa: E402

TAGS = {"m_ds": "mds_v1", "m_ds_notod": "mds_notod_v1", "m_ds_tod": "mds_tod_v1", "m_ds_3seeds": "mds_3seeds_v1"}


def predict_validate(name: str) -> pd.DataFrame:
    """Прогноз модели ``name`` (из ``models/feature_config.json``) для 151 точки validate."""
    cfg = json.loads(Path("models/feature_config.json").read_text(encoding="utf-8"))["models"][name]
    m = CatBoostRegressor()
    m.load_model(cfg["file"])
    F = load_features("validate", cfg["cur_dev_source"])
    pred = to_delay(F["cur_dev_s"].to_numpy(), m.predict(F[cfg["features"]]), cfg["base_mode"])
    return pd.DataFrame({"sample_id": F["sample_id"].astype(str), "prediction": np.round(pred, 1)})


def _metrics(name: str) -> tuple[float | None, float | None]:
    card = json.loads(Path("models/model_card.json").read_text(encoding="utf-8"))["m_ds"]
    notod = name == "m_ds_notod" or (name in ("m_ds", "m_ds_3seeds") and card["submission_variant"] == "notod")
    return (card["official_mae_notod"], card["lobo_mae_notod"]) if notod else (card["official_mae_tod"], card["lobo_mae"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="m_ds", choices=sorted(TAGS))
    args = ap.parse_args(argv)
    sub = predict_validate(args.model)
    test_mae, lobo_mae = _metrics(args.model)
    path = save_submission(sub, TAGS[args.model], args.model, "v1", test_mae, lobo_mae)
    errors = validate(path)
    print(f"{path.relative_to(ROOT).as_posix()}: {'OK' if not errors else errors}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
