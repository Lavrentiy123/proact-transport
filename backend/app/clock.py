"""Часы симуляции: время датасета, которое идёт со скоростью ``speed`` относительно реального.

Время симуляции — float-секунды «наивного» времени датасета, прочитанного как UTC (как в
:func:`features.to_epoch_s`). Эмулятор NDTP всегда ставит в пакет текущее время (проверено на
образе), поэтому такие метки переводятся в время симуляции по моменту прихода (:meth:`to_sim`).
"""

from __future__ import annotations

import time

from features import from_epoch_s, to_epoch_s

REPLAY_WINDOW_S = 6 * 3600.0   # метка ближе этого к времени симуляции считается временем датасета


class SimClock:
    """Время симуляции ``sim = anchor_sim + (wall − anchor_wall) · speed``.

    Args:
        start_at: начальный момент симуляции (строка/datetime/секунды).
        speed: во сколько раз симуляция быстрее реального времени.
        wall: источник реального времени (для тестов).
    """

    def __init__(self, start_at, speed: float = 1.0, wall=time.time):
        self._wall = wall
        self.speed = float(speed)
        self.anchor_sim = to_epoch_s(start_at)
        self.anchor_wall = self._wall()
        self.epoch = 0   # растёт при переносе начала (сброс состояния бортов)

    def now_s(self) -> float:
        """Текущее время симуляции, секунды."""
        return self.anchor_sim + (self._wall() - self.anchor_wall) * self.speed

    def now(self):
        """Текущее время симуляции как наивный ``pd.Timestamp``."""
        return from_epoch_s(self.now_s())

    def sim_at_wall(self, wall_s: float) -> float:
        """Время симуляции, соответствующее моменту реального времени ``wall_s``."""
        return self.anchor_sim + (wall_s - self.anchor_wall) * self.speed

    def to_sim(self, packet_ts: float) -> float:
        """Метка пакета → время симуляции.

        Метка времени датасета (наш replay) используется как есть; метка реального времени
        (эмулятор) переводится по часам.
        """
        now = self.now_s()
        if abs(packet_ts - now) <= REPLAY_WINDOW_S:
            return float(packet_ts)
        return self.sim_at_wall(float(packet_ts))

    def set(self, start_at=None, speed: float | None = None) -> bool:
        """Меняет скорость и/или переносит начало. Возвращает ``True``, если начало перенесено."""
        now_wall = self._wall()
        current = self.anchor_sim + (now_wall - self.anchor_wall) * self.speed
        moved = start_at is not None
        self.anchor_sim = to_epoch_s(start_at) if moved else current
        self.anchor_wall = now_wall
        if speed is not None:
            self.speed = float(speed)
        if moved:
            self.epoch += 1
        return moved
