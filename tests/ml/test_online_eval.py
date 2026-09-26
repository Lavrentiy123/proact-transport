"""ML-T6: онлайн-replay отрабатывает на 2 бортах, горизонт соблюдается, онлайн-MAE конечен."""
import math
from pathlib import Path

import numpy as np
import pytest


@pytest.mark.slow
def test_online_replay_two_buses():
    import pandas as pd

    from src.eval.online_replay_eval import run_replay, summarize

    labels = pd.read_csv(Path(__file__).resolve().parents[2] / "data" / "labels" / "labels_test.csv")
    buses = sorted(int(x) for x in labels.tr_id.unique())[:2]
    log = run_replay(buses, tick_s=300)
    built = log[log.built]
    assert len(built) > 20
    assert ((built.lead_s >= 600) & (built.lead_s <= 900)).all()
    m = summarize(log)
    assert m["share_lead_in_window"] == 1.0
    assert math.isfinite(m["online_mae_model_s"]) and m["resolved_total"] > 10
    assert np.isfinite(built.pred).all()
    assert (built.q10 <= built.pred).all() and (built.pred <= built.q90).all()
