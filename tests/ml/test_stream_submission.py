"""ML-T9: сабмит из потока — признаки OnlineVehicle по validate совпадают с офлайновыми, порядок прихода учтён."""
import numpy as np
import pytest

from features import FEATURE_NAMES


@pytest.mark.slow
def test_stream_event_order_equals_offline_reconstructed():
    from src.ml.dataset import load_features
    from src.ml.stream_submission import stream_features

    S = stream_features("validate", "event")
    F = load_features("validate", "reconstructed")
    assert len(S) == len(F) == 151 and list(S.sample_id) == list(F.sample_id)
    A = np.array([[s[n] for n in FEATURE_NAMES] for s in S.feats], dtype=np.float64)
    B = F[FEATURE_NAMES].to_numpy(np.float64)
    assert np.allclose(A, B, equal_nan=True, atol=1e-6)


@pytest.mark.slow
def test_stream_receive_order_builds_all_points():
    from src.ml.stream_submission import stream_features

    S = stream_features("validate", "receive")
    assert len(S) == 151
    assert all(f is not None and list(f) == FEATURE_NAMES for f in S.feats)


def test_packet_available_after_both_receive_and_event_time(tmp_path):
    from src.ml.stream_submission import load_packets

    csv = tmp_path / "traffic.csv"
    csv.write_text("tr_id,event_time,receive_time,location_valid,lat,lon,speed,heading\n"
                   "1,2026-01-06 10:00:10,2026-01-06 10:00:00,True,55.7,37.6,10,0\n"   # часы борта впереди сервера
                   "1,2026-01-06 10:00:00,2026-01-06 10:03:00,True,55.7,37.6,10,0\n",  # пришёл с опозданием
                   encoding="utf-8")
    P = load_packets(csv, {1})
    assert list(P.rt - P.t) == [0.0, 180.0]
