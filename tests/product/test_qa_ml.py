"""ML-P3: шпаргалка — 15 вопросов, без плейсхолдеров, числа из model_card."""
import json
import re
from pathlib import Path

from src.product.render_qa import render

ROOT = Path(__file__).resolve().parents[2]


def test_qa_has_15_questions_without_placeholders():
    text = (ROOT / "docs" / "pitch" / "qa_ml.md").read_text(encoding="utf-8")
    assert len(re.findall(r"^## \d+\. ", text, flags=re.M)) == 15
    assert "TODO" not in text and "XXX" not in text


def test_qa_generated_from_card():
    card = json.loads((ROOT / "models" / "model_card.json").read_text(encoding="utf-8"))
    assert (ROOT / "docs" / "pitch" / "qa_ml.md").read_text(encoding="utf-8") == render(card)
