"""Сохранение сабмитов в ``submissions/`` и журнал ``submissions/journal.csv``.

Имя файла: ``submissions/sub_<YYYYmmdd_HHMM>_<tag>.csv``. Колонки журнала:
``created_at, file, git_hash, model, features_version, test_mae, lobo_mae, lb_score``
(``lb_score`` заполняет пользователь после загрузки на платформу).
"""

from __future__ import annotations

import csv
import subprocess
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SUB_DIR = ROOT / "submissions"
JOURNAL = SUB_DIR / "journal.csv"
JOURNAL_COLUMNS = ["created_at", "file", "git_hash", "model", "features_version", "test_mae", "lobo_mae", "lb_score"]


def git_hash_short(mark_dirty: bool = False) -> str:
    """Короткий хеш текущего коммита (``unknown``, если git недоступен).

    Args:
        mark_dirty: добавить ``-dirty``, если в рабочем дереве есть незакоммиченные изменения
            (для журнала сабмитов: модели обычно коммитятся после генерации сабмита).
    """
    try:
        h = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                           text=True, check=True).stdout.strip()
        if mark_dirty and subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True,
                                         text=True, check=True).stdout.strip():
            h += "-dirty"
        return h
    except Exception:
        return "unknown"


def save_submission(df: pd.DataFrame, tag: str, model: str, features_version: str,
                    test_mae: float | None = None, lobo_mae: float | None = None) -> Path:
    """Пишет сабмит (UTF-8 без BOM, ``;``, LF) и добавляет строку в журнал.

    Args:
        df: колонки ``sample_id, prediction``.
        tag: суффикс имени файла.
        model, features_version: что записать в журнал.
        test_mae, lobo_mae: метрики для журнала (если есть).

    Returns:
        Путь к сохранённому файлу.
    """
    SUB_DIR.mkdir(exist_ok=True)
    now = datetime.now()
    path = SUB_DIR / f"sub_{now:%Y%m%d_%H%M}_{tag}.csv"
    out = df[["sample_id", "prediction"]].copy()
    out["sample_id"] = out["sample_id"].astype(str)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        out.to_csv(fh, sep=";", index=False, lineterminator="\n")
    new = not JOURNAL.exists()
    with open(JOURNAL, "a", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        if new:
            w.writerow(JOURNAL_COLUMNS)
        w.writerow([now.isoformat(timespec="seconds"), path.relative_to(ROOT).as_posix(), git_hash_short(mark_dirty=True), model,
                    features_version, "" if test_mae is None else f"{test_mae:.2f}",
                    "" if lobo_mae is None else f"{lobo_mae:.2f}", ""])
    return path
