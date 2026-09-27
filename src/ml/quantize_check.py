"""Проверка int8-квантования ONNX-члена ансамбля (доп. фича организаторов: «квантование, ONNX, TensorRT»).

Запуск из корня: ``.venv312/Scripts/python.exe -m src.ml.quantize_check``.

Динамическое int8-квантование весов (onnxruntime) сравнивается с fp32 по размеру, расхождению прогнозов
и латентности (1 поток, как в ml-core). Итог пишется в ``models/model_card.json → m_online_mlp.quantization_int8``;
в сервис идёт та версия, что быстрее и точнее (для нашей крошечной MLP — fp32).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from ml_core.app.predictor import onnx_session  # noqa: E402
from ml_core.inference import mlp_transform  # noqa: E402
from src.ml.dataset import load_pool  # noqa: E402


def _p50_ms(sess, X: np.ndarray, n: int = 200) -> float:
    sess.run(None, {"x": X})
    ts = []
    for _ in range(n):
        t0 = time.perf_counter()
        sess.run(None, {"x": X})
        ts.append(time.perf_counter() - t0)
    return 1000.0 * float(np.median(ts))


def main() -> dict:
    from onnxruntime.quantization import QuantType, quantize_dynamic

    cfg = json.loads(Path("models/feature_config.json").read_text(encoding="utf-8"))
    prep, feats = cfg["blend"]["mlp"], cfg["models"]["m_online"]["features"]
    with tempfile.TemporaryDirectory() as tmp:  # ASCII-путь: quantize_dynamic не любит кириллицу
        src, dst = Path(tmp) / "fp32.onnx", Path(tmp) / "int8.onnx"
        shutil.copy(Path(prep["file"]), src)
        quantize_dynamic(str(src), str(dst), weight_type=QuantType.QInt8)
        size32, size8 = src.stat().st_size, dst.stat().st_size
        s32, s8 = onnx_session(src.read_bytes()), onnx_session(dst.read_bytes())
    pool = load_pool("reconstructed")
    Z = mlp_transform(pool[feats].to_numpy(np.float64), prep)
    a, b = s32.run(None, {"x": Z})[0].ravel(), s8.run(None, {"x": Z})[0].ravel()
    d = np.abs(a - b)
    res = {
        "size_kb_fp32": round(size32 / 1024, 1), "size_kb_int8": round(size8 / 1024, 1),
        "pred_abs_diff_mean_s": round(float(d.mean()), 2), "pred_abs_diff_p99_s": round(float(np.percentile(d, 99)), 2),
        "latency_batch30_ms_fp32": round(_p50_ms(s32, Z[:30]), 3), "latency_batch30_ms_int8": round(_p50_ms(s8, Z[:30]), 3),
        "latency_batch150_ms_fp32": round(_p50_ms(s32, Z[:150]), 3), "latency_batch150_ms_int8": round(_p50_ms(s8, Z[:150]), 3),
    }
    gain30 = res["latency_batch30_ms_fp32"] - res["latency_batch30_ms_int8"]
    if res["pred_abs_diff_mean_s"] < 2 and gain30 > 0:
        res["decision"] = f"int8: быстрее на {gain30:.3f} мс (батч 30) при расхождении в пределах шума"
    else:
        res["decision"] = (f"fp32: int8 меняет прогноз в среднем на {res['pred_abs_diff_mean_s']} с (p99 "
                           f"{res['pred_abs_diff_p99_s']} с), а выигрыш по времени на батче 30 — {gain30:+.3f} мс "
                           "(доли миллисекунды, в пределах шума замера) — в сервисе остаётся fp32 ONNX")
    card_path = Path("models/model_card.json")
    card = json.loads(card_path.read_text(encoding="utf-8"))
    card.setdefault("m_online_mlp", {})["quantization_int8"] = res
    card_path.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False))
    return res


if __name__ == "__main__":
    main()
