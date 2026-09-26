"""Убирает абсолютный путь к репозиторию из сгенерированной pdoc-документации.

pdoc печатает значения по умолчанию констант вроде ``ROOT = Path(__file__).parents[2]``, и в HTML попадает
путь на машине, где собирали документацию (с именем пользователя). Скрипт заменяет его на нейтральный.

Запуск из корня репозитория после pdoc: ``python scripts/sanitize_docs.py [docs/api]``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEUTRAL = "D:/proact-transport"


def variants(path: Path) -> list[str]:
    """Все написания пути, которые встречаются в HTML и в ``search.js`` (JSON с ``\\uXXXX``)."""
    win, posix = str(path), path.as_posix()
    out = {win, posix, win.replace("\\", "\\\\")}
    for v in (win, posix):
        out.add(json.dumps(v)[1:-1])
        out.add(json.dumps(v, ensure_ascii=False)[1:-1])
    return sorted(out, key=len, reverse=True)


def sanitize(docs_dir: Path) -> int:
    """Заменяет путь во всех ``*.html`` и ``*.js``; возвращает число изменённых файлов."""
    vs = [v for v in variants(ROOT) if v]
    changed = 0
    for p in [*docs_dir.rglob("*.html"), *docs_dir.rglob("*.js")]:
        s = p.read_text(encoding="utf-8")
        t = s
        for v in vs:
            t = t.replace(v, NEUTRAL)
        if t != s:
            p.write_text(t, encoding="utf-8", newline="\n")
            changed += 1
    return changed


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "api"
    print(f"sanitize_docs: {sanitize(target)} files cleaned in {target}")
