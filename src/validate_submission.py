"""Валидатор сабмита для раздела Data Science.

Использование: ``python src/validate_submission.py <file.csv>`` — exit 0, если файл годен, иначе 1.

Проверки: UTF-8 без BOM, разделитель ``;``, заголовок ``sample_id;prediction``, ровно 151 строка
данных, множество ``sample_id`` совпадает с ``data/validate/points.csv`` без дублей,
``prediction`` — конечное число в диапазоне [−1000, 1500].
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

POINTS_CSV = Path(__file__).resolve().parents[1] / "data" / "validate" / "points.csv"
HEADER = "sample_id;prediction"
N_ROWS = 151
PRED_MIN, PRED_MAX = -1000.0, 1500.0


def _expected_ids(points_csv: Path) -> list[str]:
    lines = points_csv.read_text(encoding="utf-8").splitlines()
    cols = lines[0].split(",")
    i = cols.index("sample_id")
    return [ln.split(",")[i] for ln in lines[1:] if ln.strip()]


def validate(path: str | Path, points_csv: str | Path = POINTS_CSV) -> list[str]:
    """Проверяет файл сабмита.

    Args:
        path: путь к CSV сабмита.
        points_csv: эталонный ``points.csv`` с ожидаемыми ``sample_id``.

    Returns:
        Список ошибок (пустой — файл годен).
    """
    raw = Path(path).read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        return ["BOM: файл начинается с UTF-8 BOM, сохраните без BOM"]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        return [f"кодировка: файл не в UTF-8 ({e})"]

    lines = text.splitlines()  # \r\n допустим
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return ["пустой файл"]

    errors: list[str] = []
    if lines[0] != HEADER:
        if "," in lines[0] and ";" not in lines[0]:
            return [f"разделитель: ожидается ';', в заголовке найдено ',' ({lines[0]!r})"]
        return [f"заголовок: ожидается {HEADER!r}, получено {lines[0]!r}"]

    data = lines[1:]
    if len(data) != N_ROWS:
        errors.append(f"число строк: ожидается {N_ROWS}, получено {len(data)}")

    ids: list[str] = []
    for n, ln in enumerate(data, start=2):
        parts = ln.split(";")
        if len(parts) != 2:
            errors.append(f"строка {n}: ожидается 2 поля через ';', получено {len(parts)}: {ln!r}")
            continue
        sid, pred = parts[0].strip(), parts[1].strip()
        ids.append(sid)
        try:
            v = float(pred)
        except ValueError:
            errors.append(f"строка {n}: prediction не число: {pred!r}")
            continue
        if not math.isfinite(v):
            errors.append(f"строка {n}: prediction не конечное: {pred!r}")
        elif not PRED_MIN <= v <= PRED_MAX:
            errors.append(f"строка {n}: prediction {v} вне [{PRED_MIN:g}, {PRED_MAX:g}]")

    seen: set[str] = set()
    dups = sorted({s for s in ids if s in seen or seen.add(s)})
    if dups:
        errors.append(f"дубли sample_id ({len(dups)}): {dups[:5]}")
    expected = set(_expected_ids(Path(points_csv)))
    missing = sorted(expected - set(ids))
    extra = sorted(set(ids) - expected)
    if missing:
        errors.append(f"нет sample_id из points.csv ({len(missing)}): {missing[:5]}")
    if extra:
        errors.append(f"лишние sample_id ({len(extra)}): {extra[:5]}")
    return errors


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python src/validate_submission.py <file.csv>")
        return 1
    errors = validate(argv[1])
    if errors:
        print(f"FAIL {argv[1]}")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"OK {argv[1]}: {N_ROWS} строк, формат верный")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
