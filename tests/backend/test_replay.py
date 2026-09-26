"""BE-4 (A3): replay ``data/test/traffic.csv`` → NDTP → TCP; координаты совпадают с CSV."""

import asyncio
from collections import defaultdict

import numpy as np
import pytest

from backend.app.clock import SimClock
from backend.app.config import ROOT
from backend.app.ndtp.codec import FrameDecoder
from backend.app.replay import ReplayClient, load_rows
from features import to_epoch_s

START = "2026-01-06T07:00:00"


@pytest.fixture(scope="module")
def rows():
    return load_rows(ROOT / "data" / "test" / "traffic.csv")


async def _collect(rows, speed, duration_wall_s, preroll_s):
    frames, handshakes, peers = [], [], set()

    async def handle(reader, writer):
        dec = FrameDecoder()
        peers.add(writer.get_extra_info("peername"))
        while data := await reader.read(65536):
            for fr in dec.feed(data):
                (handshakes if fr.is_handshake else frames).append(fr)
        writer.close()

    srv = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = srv.sockets[0].getsockname()[1]
    client = ReplayClient(rows, "127.0.0.1", port, SimClock(START, speed), preroll_s=preroll_s)
    await client.run(duration_wall_s=duration_wall_s)
    await asyncio.sleep(0.3)
    srv.close()
    await srv.wait_closed()
    return client, frames, handshakes, peers


def test_rows_sorted_by_send_time_not_before_event(rows):
    assert np.all(np.diff(rows.send_s) >= 0)
    assert np.all(rows.send_s >= rows.ts)
    assert len(np.unique(rows.unit)) == 30


def test_replay_x20_30s_sim_matches_csv(rows):
    # 1.5 с реального времени × 20 = 30 с симуляции
    client, frames, handshakes, peers = asyncio.run(_collect(rows, 20.0, 1.5, preroll_s=0.0))
    t0 = to_epoch_s(START)
    expect = (rows.send_s > t0) & (rows.send_s <= t0 + 25)          # точно успели отправить
    upper = (rows.send_s > t0) & (rows.send_s <= t0 + 40)          # не больше этого
    navs = [(fr.unit_id, nav) for fr in frames for nav in fr.navs]
    assert expect.sum() > 0
    assert expect.sum() <= len(navs) <= upper.sum(), (expect.sum(), len(navs), upper.sum())
    csv = defaultdict(list)
    for i in np.nonzero(upper)[0]:
        csv[(int(rows.unit[i]), int(round(rows.ts[i])))].append(i)
    for unit, nav in navs:
        cands = csv[(unit, nav.ts)]
        assert cands, (unit, nav.ts)
        ok = False
        for i in cands:
            if not rows.valid[i] or not np.isfinite(rows.lat[i]):
                ok |= not nav.valid
            else:
                ok |= nav.valid and abs(nav.lat - rows.lat[i]) < 1e-7 and abs(nav.lon - rows.lon[i]) < 1e-7
        assert ok, (unit, nav)
    # по handshake на каждый терминал, у которого были пакеты
    assert {fr.unit_id for fr in handshakes} == {u for u, _ in navs}
    assert client.dropped == 0


def test_preroll_sends_last_minutes_first(rows):
    client, frames, _, _ = asyncio.run(_collect(rows, 1.0, 0.3, preroll_s=600.0))
    t0 = to_epoch_s(START)
    n_pre = int(((rows.send_s >= t0 - 600) & (rows.send_s <= t0)).sum())
    ts = [nav.ts for fr in frames for nav in fr.navs]
    assert n_pre > 0 and len(ts) >= n_pre
    assert max(ts) <= t0 + 60          # будущего нет: разгон — только прошлое


def test_end_of_data_idles_instead_of_exit(rows):
    import time as _t

    async def go():
        srv = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
        port = srv.sockets[0].getsockname()[1]
        client = ReplayClient(rows, "127.0.0.1", port, SimClock("2026-01-07T05:00:00", 10.0), preroll_s=0.0)
        t0 = _t.time()
        await client.run(duration_wall_s=0.6)
        srv.close()
        return client, _t.time() - t0

    client, took = asyncio.run(go())
    assert client.ended and took >= 0.55     # данные кончились, но цикл не вышел раньше срока
