"""BE-2: NDTP-кодек — round-trip, реальные кадры эмулятора, устойчивость к CRC и мусору.

Фикстура ``fixtures/emulator_frames.bin`` — 20 кадров, записанных с официального образа
``ndtp-telemetry-emulator:1.0`` (два юнита ``autoGenerate``, ``intervalMs: 2000``): ``docker load -i
data/ndtp-telemetry-emulator.tar``; ``docker run --rm -p 18080:18080 --add-host=host.docker.internal:host-gateway
ndtp-telemetry-emulator:1.0``; ``POST /api/config`` с ``targetHost=host.docker.internal``, ``targetPort=9201``;
TCP-сервер на :9201 пишет байты каждого соединения подряд (у каждого соединения — целые кадры).
"""

import random
from pathlib import Path

import pytest

from backend.app.ndtp.codec import (NAV, NPL, DecodeStats, FrameDecoder, crc16_modbus, encode_handshake, encode_nav,
                                    iter_frames, parse_frame, swap16)

FIXTURE = Path(__file__).parent / "fixtures" / "emulator_frames.bin"


def test_crc16_modbus_reference():
    # эталон CRC-16/MODBUS для ASCII "123456789" — 0x4B37
    assert crc16_modbus(b"123456789") == 0x4B37


def _random_fix(rng: random.Random) -> dict:
    return dict(unit_id=rng.randrange(0, 2**31), rid=rng.randrange(0, 2**32), ts=rng.randrange(0, 2**32),
                lat=round(rng.uniform(-90, 90), 7), lon=round(rng.uniform(-180, 180), 7),
                speed=rng.randrange(0, 200), course=rng.randrange(0, 360), valid=rng.random() < 0.8,
                alt=rng.randrange(0, 1000))


def test_round_trip_1000_random_frames():
    rng = random.Random(42)
    fixes = [_random_fix(rng) for _ in range(1000)]
    blob = b"".join(encode_nav(**f) for f in fixes)
    st = DecodeStats()
    frames, rest = iter_frames(blob, st)
    assert rest == b"" and st.frames == 1000 and st.crc_errors == 0 and st.garbage_bytes == 0
    for f, fr in zip(fixes, frames):
        assert fr.is_realtime and fr.unit_id == f["unit_id"] and fr.request_id == f["rid"]
        nav = fr.navs[0]
        assert nav.ts == f["ts"] and nav.speed == f["speed"] and nav.course == f["course"] and nav.alt == f["alt"]
        assert nav.valid == f["valid"]
        assert abs(nav.lat - f["lat"]) < 1e-7 and abs(nav.lon - f["lon"]) < 1e-7


def test_round_trip_handshake():
    fr = parse_frame(encode_handshake(1166336, rid=7))
    assert fr.is_handshake and fr.unit_id == 1166336 and fr.request_id == 7
    assert fr.handshake == {"proto_high": 6, "proto_low": 2, "flags": 0, "peer_address": 1166336,
                            "max_packet_size": 65535}


def test_nan_coordinates_encode_as_invalid():
    fr = parse_frame(encode_nav(5, 1, 1767670500, float("nan"), float("nan"), float("nan"), float("nan"), valid=True))
    nav = fr.navs[0]
    assert nav.valid is False and nav.lat == 0 and nav.lon == 0 and nav.speed == 0


def test_emulator_fixture_parses_without_crc_errors():
    blob = FIXTURE.read_bytes()
    st = DecodeStats()
    frames, rest = iter_frames(blob, st)
    assert rest == b"" and len(frames) == 20 and st.crc_errors == 0 and st.bad_headers == 0 and st.garbage_bytes == 0
    hs = [f for f in frames if f.is_handshake]
    rt = [f for f in frames if f.is_realtime]
    assert len(hs) == 2 and len(rt) == 18
    assert {f.handshake["peer_address"] for f in hs} == {664030, 664031}
    for f in rt:
        assert f.cells == [0, 8, 16, 2, 10] and not f.unknown_cell   # набор autoGenerate
        nav = f.navs[0]
        # autoGenerate стартует около (55.70 + unitId%1000/1e4, 37.50 + …), см. спецификацию §7
        assert 55.6 < nav.lat < 55.8 and 37.4 < nav.lon < 37.6 and nav.valid
    # наш энкодер кладёт CRC так же, как эмулятор (байт-свап)
    sig, size, _f, crc_field, *_ = NPL.unpack_from(blob, 0)
    assert crc_field == swap16(crc16_modbus(blob[NPL.size:NPL.size + size]))


def test_bad_crc_is_counted_not_raised():
    good = encode_nav(1, 1, 100, 55.75, 37.61, 20, 90, True)
    bad = bytearray(encode_nav(2, 2, 200, 55.76, 37.62, 30, 180, True))
    bad[-3] ^= 0xFF                      # портим тело — CRC не сойдётся
    st = DecodeStats()
    frames, rest = iter_frames(bytes(bad) + good, st)
    assert st.crc_errors == 1 and [f.unit_id for f in frames] == [1] and rest == b""
    with pytest.raises(ValueError):
        parse_frame(bytes(bad))


def test_garbage_before_signature_resyncs():
    good = encode_nav(3, 1, 300, 55.7, 37.5, 10, 45, True)
    junk = bytes([0x00, 0x7E, 0x11, 0x7E, 0x7E, 0x01, 0x00, 0x42]) + b"random noise"
    st = DecodeStats()
    frames, rest = iter_frames(junk + good + junk + good, st)
    assert [f.unit_id for f in frames] == [3, 3]
    assert st.garbage_bytes > 0 and rest == b""


def test_stream_split_into_random_chunks():
    rng = random.Random(7)
    blob = FIXTURE.read_bytes() + b"".join(encode_nav(**_random_fix(rng)) for _ in range(200))
    dec = FrameDecoder()
    got = []
    i = 0
    while i < len(blob):
        n = rng.randrange(1, 60)
        got += dec.feed(blob[i:i + n])
        i += n
    assert len(got) == 220 and dec.stats.crc_errors == 0 and dec.pending == 0


def test_nav_struct_is_26_bytes():
    assert NAV.size == 26 and NPL.size == 15
