"""Пакет признаков «ПроАкт.Транспорт»: одни и те же признаки при обучении и на потоке.

Публичное API:

- :data:`FEATURE_NAMES`, :data:`FEATURES_VERSION` — 34 признака в фиксированном порядке;
- :func:`build_features` — признаки одной точки, :func:`build_features_batch` — набора точек;
- :class:`StopDetector` — детектор прибытий на плановые остановки;
- :class:`OnlineVehicle` — состояние борта на потоке (буфер 30 мин + детектор + признаки);
- :func:`load_traffic`, :func:`load_schedule` — чтение и нормализация данных.

Анти-утечка: признаки для ``(tr_id, T)`` используют только телеметрию с ``t ≤ T`` и плановое
расписание; факты прибытия пакет не читает.
"""

from .build import FEATURE_NAMES, FEATURES_VERSION, build_features, build_features_batch, features_from_arrays
from .geo import haversine_m, parse_point
from .io import ScheduleArrays, from_epoch_s, load_schedule, load_traffic, to_epoch_s
from .online import OnlineVehicle
from .stop_detector import StopDetector


def features_to_json(feats: dict[str, float]) -> dict[str, float | None]:
    """Заменяет NaN на ``None`` — для ``PredictRow.features`` и JSON."""
    return {k: (None if v is None or v != v else float(v)) for k, v in feats.items()}


__all__ = [
    "FEATURE_NAMES", "FEATURES_VERSION", "build_features", "build_features_batch", "features_from_arrays",
    "StopDetector", "OnlineVehicle", "load_schedule", "load_traffic", "ScheduleArrays",
    "haversine_m", "parse_point", "to_epoch_s", "from_epoch_s", "features_to_json",
]
