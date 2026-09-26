"""ML-T1: статическая проверка анти-утечки.

В коде признаков, моделей и инференса нет фактов прибытия, признака ручного ввода факта
(``manual_fill`` — атрибут факта, см. ``docs/ANTI_LEAKAGE.md``) и early stopping по test.
Факты разрешены только в ``tests/`` и ``src/eval/`` (оценка, не признаки).
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TARGETS = ["src/train.py", "features", "ml_core", "src/ml"]
FORBIDDEN = ["time_fact_begin", "eval_set=(X_test", "manual_fill"]


def _py_files():
    for t in TARGETS:
        p = ROOT / t
        if p.is_file():
            yield p
        elif p.is_dir():
            yield from sorted(p.rglob("*.py"))


@pytest.mark.parametrize("path", list(_py_files()), ids=lambda p: str(p.relative_to(ROOT)))
def test_no_forbidden_substrings(path):
    text = path.read_text(encoding="utf-8")
    for s in FORBIDDEN:
        assert s not in text, f"{path.relative_to(ROOT)} содержит запрещённое {s!r}"
