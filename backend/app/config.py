"""Настройки backend из переменных окружения (значения по умолчанию — для запуска из корня репозитория)."""

from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _path(value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else ROOT / p


@dataclass
class Settings:
    """Параметры сервиса. Имя переменной окружения = имя поля в верхнем регистре."""

    ndtp_host: str = "0.0.0.0"
    ndtp_port: int = 9201
    ndtp_idle_timeout_s: float = 600.0
    schedule_path: str = "data/test/schedule.csv"   # плановое расписание (факты не читаются)
    traffic_path: str = "data/test/traffic.csv"     # только пары unit_id ↔ tr_id
    replay_start_at: str = "2026-01-06T07:00:00"    # начальное время симуляции
    replay_speed: float = 10.0
    tick_s: float = 5.0                  # период тика, секунды времени симуляции
    degraded_after_s: float = 15.0       # нет пакетов дольше — режим DEGRADED (секунды реального времени)
    stale_after_s: float = 30.0          # борт молчит дольше — stale (секунды симуляции)
    ml_url: str = ""                     # http://ml-core:8001; пусто — ml-core не используется
    ml_timeout_s: float = 1.0
    ml_fail_threshold: int = 3           # столько ошибок подряд — circuit breaker открывается
    ml_open_s: float = 30.0              # сколько секунд не звать ml-core после открытия
    emulator_api: str = ""               # http://ndtp-emulator:18080; пусто — эмулятором не управляем
    emulator_target_host: str = "backend"
    emulator_mode: str = "auto"          # auto — N случайных юнитов; trajectories — реальные треки датасета
    emulator_units: int = 3
    emulator_interval_ms: int = 5000
    emulator_unit_base: int = 900000     # unitId синтетических юнитов (нет в датасете)
    trajectory_step_s: float = 10.0      # период пере-POST в режиме trajectories, секунды симуляции
    journal_max: int = 300_000

    @classmethod
    def from_env(cls) -> "Settings":
        kw = {}
        for f in fields(cls):
            raw = os.getenv(f.name.upper())
            if raw is None or raw == "":
                continue
            typ = type(f.default)
            kw[f.name] = typ(raw) if typ is not bool else raw.lower() in {"1", "true", "yes"}
        return cls(**kw)

    @property
    def schedule_file(self) -> Path:
        return _path(self.schedule_path)

    @property
    def traffic_file(self) -> Path:
        return _path(self.traffic_path)
