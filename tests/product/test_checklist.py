"""ML-P4: все пути из чек-листа существуют в репозитории (кроме внешних ссылок)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_checklist_paths_exist():
    text = (ROOT / "docs" / "SUBMISSION_CHECKLIST.md").read_text(encoding="utf-8")
    paths = set(re.findall(r"`((?:docs|src|submissions|models|ml_core|scripts|features)/[^`\s]*)`", text))
    assert paths, "в чек-листе нет путей"
    missing = [p for p in sorted(paths) if not (ROOT / p.split("#")[0]).exists()]
    assert not missing, missing


def test_checklist_best_submission_exists():
    text = (ROOT / "docs" / "SUBMISSION_CHECKLIST.md").read_text(encoding="utf-8")
    subs = re.findall(r"submissions/sub_\d{8}_\d{4}_\w+\.csv", text)
    assert subs and all((ROOT / s).exists() for s in subs)
