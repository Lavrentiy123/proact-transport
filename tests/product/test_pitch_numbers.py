"""ML-P1: цифры в слайдах совпадают с models/model_card.json (файл сгенерирован скриптом)."""
import json
from pathlib import Path

from src.product.render_accuracy import render

ROOT = Path(__file__).resolve().parents[2]


def test_accuracy_slides_match_model_card():
    card = json.loads((ROOT / "models" / "model_card.json").read_text(encoding="utf-8"))
    text = (ROOT / "docs" / "pitch" / "01_accuracy.md").read_text(encoding="utf-8")
    assert text == render(card), "перегенерируйте: python -m src.product.render_accuracy"
    for v in (card["m_ds"]["official_mae"], card["m_ds"]["lobo_mae"], card["m_ds"]["fwd_mae"],
              card["baselines"]["official_cur_dev"]):
        assert f"{v:.1f}" in text
    assert "74.2" in text
    assert text.count("## Слайд") == 3


def test_pitch_data_files():
    for f in ("accuracy.csv", "causes.csv", "horizon.csv", "data_overview.csv"):
        assert (ROOT / "docs" / "pitch" / "data" / f).exists(), f
