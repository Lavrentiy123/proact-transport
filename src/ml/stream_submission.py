"""Сабмит из потока: validate-день через ``OnlineVehicle`` и ансамбль ml-core — так, как считает живой backend.

Запуск из корня: ``.venv312/Scripts/python.exe -m src.ml.stream_submission`` → ``submissions/sub_<ts>_stream_v2.csv``.

Зачем: организаторы подтверждают скор платформы потоковым решением (чат, 25.09 17:04). Этот файл —
прогноз той же цепочки, что работает на NDTP: пакеты подаются в ``OnlineVehicle`` в порядке прихода на
сервер (``receive_time``), к моменту ``T`` известны только пришедшие пакеты с ``event_time ≤ T``,
отклонение ``cur_dev_s`` — восстановленное детектором (подсказки организаторов в NDTP нет), прогноз —
``Predictor.predict(..., "online")`` (m_online + m_sched + PyTorch/ONNX).

``--split test`` прогоняет то же по дню test и печатает MAE по ``labels_test`` (модели обучены на
train + test labels, поэтому это проверка цепочки, а не честная оценка — честная в ``model_card`` LOBO).
``--order event`` подаёт пакеты по ``event_time`` — признаки тогда совпадают с офлайновыми
(``build_features_batch(..., "reconstructed")``), по разнице видно, сколько даёт порядок прихода.

``--members cat`` — только CatBoost m_online (без m_sched и MLP). Веса ансамбля выбраны по LOBO (незнакомый
борт), а validate — тот же день и те же борта, что train/test (``docs/ANTI_LEAKAGE.md``); на official split
(печатается только для сравнения, ничего по нему не выбирается — ``src/eval/stream_official.py``) CatBoost
потока точнее ансамбля. Оба файла — доказательство потока для проверки организаторами; основной сабмит —
``m_ds``. Живой backend остаётся на ансамбле — он лучше на новых бортах.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from features import FEATURES_VERSION, OnlineVehicle, features_to_json, load_schedule  # noqa: E402
from features.io import times_to_epoch_s  # noqa: E402
from ml_core.app.predictor import Predictor  # noqa: E402
from src.submission_journal import save_submission  # noqa: E402
from src.validate_submission import validate  # noqa: E402

DATA = ROOT / "data"
SPLITS = {  # точки, телеметрия, плановое расписание (факты не читаются)
    "validate": ("validate/points.csv", "validate/traffic.csv", "validate/schedule_plan.csv"),
    "test": ("labels/labels_test.csv", "test/traffic.csv", "test/schedule.csv"),
}


def load_packets(path: Path, buses: set[int]) -> pd.DataFrame:
    """Пакеты бортов ``buses``: ``tr_id, t`` (event_time, с), ``rt`` (receive_time, с), координаты, валидность."""
    raw = pd.read_csv(path, low_memory=False, usecols=["tr_id", "event_time", "receive_time", "location_valid",
                                                          "lat", "lon", "speed", "heading"])
    raw = raw[raw.tr_id.isin(buses)].copy()
    raw["t"] = times_to_epoch_s(pd.to_datetime(raw["event_time"], format="ISO8601"))
    rt = pd.to_datetime(raw["receive_time"], format="ISO8601", errors="coerce")
    raw["rt"] = np.where(rt.notna(), times_to_epoch_s(rt.fillna(pd.Timestamp(0))), raw["t"])
    # доступен к T, если пришёл (rt ≤ T) и сам не «из будущего» (t ≤ T): у 2 % пакетов часы борта впереди сервера
    raw["rt"] = np.maximum(raw["rt"], raw["t"])
    raw["valid"] = raw["location_valid"].astype(str).str.lower().eq("true") & raw.lat.notna() & raw.lon.notna()
    return raw


def stream_features(split: str = "validate", order: str = "receive") -> pd.DataFrame:
    """Признаки точек сплита, посчитанные на потоке.

    Args:
        split: ``validate`` | ``test``.
        order: ``receive`` — пакеты в порядке ``receive_time`` (как на сервере); ``event`` — по ``event_time``.

    Returns:
        DataFrame ``sample_id, tr_id, T, feats`` (``feats`` — dict признаков) в порядке точек сплита
        (+ ``target_delay_s`` для test).
    """
    pts_csv, trf_csv, sch_csv = SPLITS[split]
    pts = pd.read_csv(DATA / pts_csv, dtype={"sample_id": str})
    pts["T_s"] = times_to_epoch_s(pd.to_datetime(pts["T"]))
    sched = load_schedule(DATA / sch_csv)
    pk = load_packets(DATA / trf_csv, set(int(b) for b in pts.tr_id.unique()))
    key = "rt" if order == "receive" else "t"
    feats: dict[int, dict] = {}
    for b, P in pts.groupby("tr_id", sort=False):
        veh = OnlineVehicle(sched[sched.tr_id == b], tr_id=int(b))
        rows = pk[pk.tr_id == b].sort_values([key, "t"], kind="stable")
        arr = rows[["t", "rt", "lat", "lon", "speed", "heading", "valid"]].to_numpy(object)
        order_key = rows[key].to_numpy(np.float64)
        j = 0
        for r in P.sort_values("T_s").itertuples():
            T = float(r.T_s)
            while j < len(arr) and order_key[j] <= T:
                t, _, la, lo, sp, hd, ok = arr[j]
                j += 1
                veh.push(float(t), float(la), float(lo), float(sp), float(hd), bool(ok))
            f = veh.features_at(T, target=(int(r.target_stop_id), r.target_time_begin))
            feats[r.Index] = f
    out = pts[["sample_id", "tr_id", "T"]].copy()
    out["feats"] = [feats[i] for i in pts.index]
    if "target_delay_s" in pts.columns:
        out["target_delay_s"] = pts["target_delay_s"].values
    return out


def predict(F: pd.DataFrame, predictor: Predictor | None = None) -> np.ndarray:
    """Прогноз задержки ансамблем ml-core (тот же код, что за ``/v1/predict``)."""
    if predictor is None:
        predictor = Predictor()
        predictor.load()
        if not predictor.ready:
            raise RuntimeError(predictor.error)
    rows = [{"tr_id": int(b), "features": features_to_json(f)} for b, f in zip(F.tr_id, F.feats)]
    res, _ = predictor.predict(rows, "online")
    return np.array([r["delay_pred_s"] for r in res], dtype=np.float64)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="validate", choices=sorted(SPLITS))
    ap.add_argument("--order", default="receive", choices=["receive", "event"])
    ap.add_argument("--members", default="ensemble", choices=["ensemble", "cat"])
    args = ap.parse_args(argv)
    predictor = Predictor()
    predictor.load()
    if args.members == "cat":
        predictor.w_mlp = predictor.w_sched = 0.0   # только CatBoost m_online
    F = stream_features(args.split, args.order)
    pred = predict(F, predictor)
    if args.split == "test":
        y = F["target_delay_s"].to_numpy(np.float64)
        print(f"test (in-sample chain check), order={args.order}, members={args.members}: MAE {np.mean(np.abs(pred - y)):.2f} s "
              f"on {len(y)} points; model {predictor.model_version}")
        return 0
    sub = pd.DataFrame({"sample_id": F["sample_id"], "prediction": np.round(pred, 1)})
    card = json.loads((ROOT / "models" / "model_card.json").read_text(encoding="utf-8"))
    so = card.get("stream_submission", {}).get("official_mae", {})
    if args.members == "cat":
        lobo, off, model = card["m_online"]["lobo_mae"], so.get("cat"), f"{predictor.model_version}-cat"
    else:
        lobo, off, model = card.get("m_online_mlp", {}).get("lobo_mae_blend"), so.get("blend"), predictor.model_version
    tag = "stream" + ("_cat" if args.members == "cat" else "") + ("_event" if args.order == "event" else "")
    path = save_submission(sub, f"{tag}_{FEATURES_VERSION}", model, FEATURES_VERSION, off, lobo)
    errors = validate(path)
    print(f"{path.relative_to(ROOT).as_posix()}: {'OK' if not errors else errors}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
