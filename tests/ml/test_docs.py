"""ML-T8: pdoc собран, model card заполнена."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_pdoc_built():
    api = ROOT / "docs" / "api" / "ml"
    assert (api / "features.html").exists()
    assert (api / "ml_core.html").exists()


def test_model_card_has_no_todo_except_lb():
    text = (ROOT / "docs" / "model_card.md").read_text(encoding="utf-8")
    assert "TODO" not in text
    assert "## Метрики" in text and "LOBO" in text


def test_anti_leakage_note_lists_existing_tests():
    text = (ROOT / "docs" / "ANTI_LEAKAGE.md").read_text(encoding="utf-8")
    for path in set(re.findall(r"`(tests/[\w/]+\.py)", text)):
        assert (ROOT / path).exists(), path
