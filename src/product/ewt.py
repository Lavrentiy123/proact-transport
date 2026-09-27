"""Ожидание пассажира на остановке: AWT, SWT, EWT и перевод в пассажиро-часы и рубли.

- ``AWT = Σh² / (2·Σh)`` — среднее фактическое ожидание при случайном подходе пассажиров;
- ``SWT = H_plan / 2`` — плановое ожидание при плановом интервале ``H_plan``;
- ``EWT = AWT − SWT`` — избыточное ожидание из-за неравномерности интервалов (метрика TfL и др.).

Все интервалы — в минутах.
"""

from __future__ import annotations

from collections.abc import Sequence


def awt(headways_min: Sequence[float]) -> float:
    """Среднее фактическое ожидание, мин: ``Σh² / (2·Σh)``.

    Raises:
        ValueError: пустой список или неположительная сумма интервалов.
    """
    h = [float(x) for x in headways_min]
    if not h:
        raise ValueError("пустой список интервалов")
    s = sum(h)
    if s <= 0 or any(x < 0 for x in h):
        raise ValueError("интервалы должны быть неотрицательными, сумма — положительной")
    return sum(x * x for x in h) / (2.0 * s)


def swt(h_plan_min: float) -> float:
    """Плановое ожидание, мин: ``H_plan / 2``."""
    if h_plan_min <= 0:
        raise ValueError("плановый интервал должен быть положительным")
    return float(h_plan_min) / 2.0


def ewt(headways_min: Sequence[float], h_plan_min: float) -> float:
    """Избыточное ожидание, мин: ``AWT − SWT``."""
    return awt(headways_min) - swt(h_plan_min)


def passenger_hours(ewt_min: float, passengers: float) -> float:
    """Потерянные пассажиро-часы: ``EWT × пассажиропоток`` (EWT в минутах → часы)."""
    return ewt_min / 60.0 * passengers


def rubles(pass_hours: float, value_of_hour_rub: float) -> float:
    """Стоимость потерянного времени, ₽: пассажиро-часы × стоимость часа."""
    return pass_hours * value_of_hour_rub
