"""Общие фикстуры тестов (ml, ml_core, product): данные test/train, загруженные один раз за сессию."""
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


@pytest.fixture(scope="session")
def test_data():
    from features import load_schedule, load_traffic

    return SimpleNamespace(
        traffic=load_traffic(DATA / "test" / "traffic.csv"),
        schedule=load_schedule(DATA / "test" / "schedule.csv"),
        labels=pd.read_csv(DATA / "labels" / "labels_test.csv", dtype={"sample_id": str}),
    )


@pytest.fixture(scope="session")
def train_data():
    from features import load_schedule, load_traffic

    return SimpleNamespace(
        traffic=load_traffic(DATA / "train" / "traffic.csv"),
        schedule=load_schedule(DATA / "train" / "schedule.csv"),
        labels=pd.read_csv(DATA / "labels" / "labels_train.csv", dtype={"sample_id": str}),
    )
