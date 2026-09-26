"""ML-T0: окружение .venv312 собрано, контракты импортируются."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_python_version():
    assert sys.version_info >= (3, 12)


def test_core_imports():
    import catboost  # noqa: F401
    import fastapi  # noqa: F401
    import numpy  # noqa: F401
    import onnxruntime  # noqa: F401
    import pandas  # noqa: F401
    import pydantic  # noqa: F401
    import sklearn  # noqa: F401


def test_ws_snapshot_example_matches_contract():
    from contracts.schemas import WsMessage

    raw = json.loads((ROOT / "contracts" / "examples" / "ws_snapshot.json").read_text(encoding="utf-8"))
    msg = WsMessage.model_validate(raw)
    assert msg.type == "snapshot"
