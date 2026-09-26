"""Геометрия: расстояния по большому кругу и разбор WKT-точек."""

from __future__ import annotations

import math
import re

import numpy as np

R_EARTH_M = 6_371_000.0
_POINT_RE = re.compile(r"POINT\s*\(\s*([-\d.eE+]+)\s+([-\d.eE+]+)\s*\)")


def haversine_m(lon1, lat1, lon2, lat2):
    """Расстояние по большому кругу в метрах, векторно (numpy broadcasting).

    Args:
        lon1, lat1: долгота и широта первой точки (градусы), скаляры или массивы.
        lon2, lat2: долгота и широта второй точки (градусы).

    Returns:
        ``np.ndarray`` (или скаляр ``np.float64``) расстояний в метрах, R = 6 371 000 м.
    """
    lon1, lat1, lon2, lat2 = (np.radians(np.asarray(x, dtype=np.float64)) for x in (lon1, lat1, lon2, lat2))
    a = np.sin((lat2 - lat1) / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2.0) ** 2
    return 2.0 * R_EARTH_M * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def haversine_scalar_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """То же, что :func:`haversine_m`, для одной пары точек (быстрее numpy на скалярах)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2.0) ** 2
    return 2.0 * R_EARTH_M * math.asin(math.sqrt(min(max(a, 0.0), 1.0)))


def parse_point(s: str) -> tuple[float, float]:
    """Разбирает строку ``"POINT (lon lat)"``.

    Returns:
        ``(lon, lat)``; ``(nan, nan)``, если строка не разобрана.
    """
    m = _POINT_RE.search(s) if isinstance(s, str) else None
    if not m:
        return math.nan, math.nan
    return float(m.group(1)), float(m.group(2))
