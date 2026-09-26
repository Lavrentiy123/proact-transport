"""ML-T1: валидатор сабмита ловит типовые ошибки формата."""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from validate_submission import validate  # noqa: E402


@pytest.fixture
def good_lines() -> list[str]:
    lines = (ROOT / "data" / "sample_submission.csv").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "sample_id;prediction"
    return lines


def _write(tmp_path, lines, name="sub.csv", bom=False, sep="\n"):
    p = tmp_path / name
    data = sep.join(lines) + sep
    p.write_bytes((b"\xef\xbb\xbf" if bom else b"") + data.encode("utf-8"))
    return p


def test_good_file_passes(tmp_path, good_lines):
    assert validate(_write(tmp_path, good_lines)) == []


def test_crlf_allowed(tmp_path, good_lines):
    assert validate(_write(tmp_path, good_lines, sep="\r\n")) == []


def test_missing_row(tmp_path, good_lines):
    errs = validate(_write(tmp_path, good_lines[:-1]))
    assert any("число строк" in e for e in errs)
    assert any("нет sample_id" in e for e in errs)


def test_duplicate(tmp_path, good_lines):
    lines = good_lines[:-1] + [good_lines[1]]
    errs = validate(_write(tmp_path, lines))
    assert any("дубли" in e for e in errs)


def test_nan(tmp_path, good_lines):
    lines = list(good_lines)
    lines[5] = lines[5].split(";")[0] + ";nan"
    errs = validate(_write(tmp_path, lines))
    assert any("строка 6" in e and "не конечное" in e for e in errs)


def test_out_of_range(tmp_path, good_lines):
    lines = list(good_lines)
    lines[3] = lines[3].split(";")[0] + ";5000"
    assert any("вне" in e for e in validate(_write(tmp_path, lines)))


def test_comma_separator(tmp_path, good_lines):
    lines = [ln.replace(";", ",") for ln in good_lines]
    errs = validate(_write(tmp_path, lines))
    assert errs and "разделитель" in errs[0]


def test_wrong_header(tmp_path, good_lines):
    lines = ["id;prediction"] + good_lines[1:]
    errs = validate(_write(tmp_path, lines))
    assert errs and "заголовок" in errs[0]


def test_bom(tmp_path, good_lines):
    errs = validate(_write(tmp_path, good_lines, bom=True))
    assert errs and "BOM" in errs[0]


def test_extra_row(tmp_path, good_lines):
    lines = good_lines + ["999_1767670500;1.0"]
    errs = validate(_write(tmp_path, lines))
    assert any("число строк" in e for e in errs)
    assert any("лишние" in e for e in errs)


def test_cli_exit_codes(tmp_path, good_lines):
    ok = subprocess.run([sys.executable, str(ROOT / "src" / "validate_submission.py"), str(_write(tmp_path, good_lines))])
    bad = subprocess.run(
        [sys.executable, str(ROOT / "src" / "validate_submission.py"), str(_write(tmp_path, good_lines[:-1], name="b.csv"))],
        capture_output=True,
    )
    assert ok.returncode == 0
    assert bad.returncode == 1
