"""ML-P2: калькулятор EWT."""
import pytest

from src.product.ewt import awt, ewt, passenger_hours, rubles, swt


def test_equal_headways_zero_ewt():
    assert ewt([8, 8, 8, 8], 8) == pytest.approx(0.0)


def test_uneven_headways_example():
    assert awt([2, 14]) == pytest.approx((4 + 196) / 32) == pytest.approx(6.25)
    assert swt(8) == 4.0
    assert ewt([2, 14], 8) == pytest.approx(2.25)


def test_empty_raises():
    with pytest.raises(ValueError):
        awt([])


def test_money_chain():
    ph = passenger_hours(2.25, 1000)
    assert ph == pytest.approx(37.5)
    assert rubles(ph, 400) == pytest.approx(15000)


def test_business_doc_numbers_match_demo():
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    d = json.loads((root / "reports" / "business_demo.json").read_text(encoding="utf-8"))
    doc = (root / "docs" / "business_effect.md").read_text(encoding="utf-8")
    for v in (d["awt_fact_min"], d["awt_after_min"], d["ewt_fact_min"], d["ewt_after_min"]):
        assert f"{v:.2f}" in doc
    assert f"{d['ewt_reduction_min']:.2f}" in doc
    assert f"{d['n_holds']} раз" in doc
    assert "допущение" in doc and "https://" in doc
