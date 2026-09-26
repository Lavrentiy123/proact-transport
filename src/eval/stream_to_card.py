"""Переносит замеры живого потока (``scripts/measure_perf.py load``) в ``models/model_card.json → stream_live``.

Запуск из корня (стек поднят, прогон уже сделан):
``.venv312/Scripts/python.exe -m src.eval.stream_to_card reports/logs/perf_load_after_T5_ensemble.jsonl``.

Это доказательство критерия 2 «на потоке»: горизонт и онлайн-MAE считает backend по журналу прогнозов,
сверенному с прибытиями, которые зафиксировал сам поток (детектор), — а не офлайн-выгрузка.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KEYS = {
    "horizon_share_in_window": "share_lead_in_window",
    'online_mae_seconds{model="forecast"}': "online_mae_model_s",
    'online_mae_seconds{model="baseline_cur_dev"}': "online_mae_baseline_s",
    "journal_resolved_total": "resolved_total",
    'infer_ms{quantile="0.5"}': "infer_ms_p50",
    'infer_ms{quantile="0.99"}': "infer_ms_p99",
    'tick_duration_ms{quantile="0.5"}': "tick_ms_p50",
    'tick_duration_ms{quantile="0.99"}': "tick_ms_p99",
    "tick_overruns_total": "tick_overruns",
    "ndtp_crc_errors_total": "crc_errors",
}


def main(argv: list[str]) -> dict:
    src = Path(argv[1]) if len(argv) > 1 else ROOT / "reports" / "logs" / "perf_load_after_T5_ensemble.jsonl"
    metrics = {}
    for line in src.read_text(encoding="utf-8-sig").splitlines():  # вывод из PowerShell бывает с BOM
        if line.strip():
            d = json.loads(line)
            if d["metric"] in KEYS:
                metrics[KEYS[d["metric"]]] = round(float(d["value"]), 2)
    card_path = ROOT / "models" / "model_card.json"
    card = json.loads(card_path.read_text(encoding="utf-8"))
    card["stream_live"] = {**metrics, "setup": "docker compose, replay дня 06.01 ×10 по NDTP, 8 мин, ноутбук i5-10210U",
                           "model_version": card.get("model_version"), "source": src.relative_to(ROOT).as_posix()}
    card_path.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(card["stream_live"], ensure_ascii=False))
    return card["stream_live"]


if __name__ == "__main__":
    main(sys.argv)
