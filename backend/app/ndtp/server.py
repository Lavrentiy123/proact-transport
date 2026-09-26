"""TCP-сервер NDTP (по умолчанию :9201): эмулятор и replay подключаются к нему как бортовые терминалы.

На каждое соединение — свой :class:`FrameDecoder`; счётчики общие. Ответы терминалу не
отправляются: эмулятор их не разбирает (спецификация §4). Битый кадр отбрасывается, соединение
живёт; соединение без данных дольше ``idle_timeout_s`` закрывается (терминал переподключится).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

from .codec import DecodeStats, Frame, FrameDecoder

log = logging.getLogger("backend.ndtp")


class NdtpServer:
    """Приём кадров NDTP по TCP.

    Args:
        on_frame: вызывается для каждого разобранного кадра: ``on_frame(frame)``.
        host, port: адрес прослушивания (``port=0`` — свободный порт, см. :attr:`port`).
        idle_timeout_s: закрыть соединение без данных дольше этого.
    """

    def __init__(self, on_frame: Callable[[Frame], None], host: str = "0.0.0.0", port: int = 9201,
                 idle_timeout_s: float = 600.0):
        self.on_frame = on_frame
        self.host = host
        self.port = port
        self.idle_timeout_s = idle_timeout_s
        self.stats = DecodeStats()
        self.sessions = 0
        self.connections_total = 0
        self.handshakes = 0
        self.realtime_packets = 0
        self.nav_fixes = 0
        self.handler_errors = 0
        self.last_packet_wall: float | None = None
        self._server: asyncio.base_events.Server | None = None
        self._writers: set[asyncio.StreamWriter] = set()

    @property
    def listening(self) -> bool:
        return self._server is not None and self._server.is_serving()

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, self.host, self.port)
        self.port = self._server.sockets[0].getsockname()[1]
        log.info("NDTP server listening on %s:%s", self.host, self.port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            for w in list(self._writers):
                w.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        self.sessions += 1
        self.connections_total += 1
        self._writers.add(writer)
        dec = FrameDecoder(self.stats)
        try:
            while True:
                data = await asyncio.wait_for(reader.read(65536), timeout=self.idle_timeout_s)
                if not data:
                    break
                for fr in dec.feed(data):
                    if fr.is_handshake:
                        self.handshakes += 1
                    elif fr.is_realtime:
                        self.realtime_packets += 1
                        self.nav_fixes += len(fr.navs)
                        self.last_packet_wall = time.time()
                    try:
                        self.on_frame(fr)
                    except Exception:   # ошибка обработки одного пакета не рвёт соединение
                        self.handler_errors += 1
                        log.exception("frame handler failed (unit %s)", fr.unit_id)
        except (asyncio.TimeoutError, ConnectionError, OSError) as e:
            log.info("NDTP connection %s closed: %s", peer, type(e).__name__)
        finally:
            self.sessions -= 1
            self._writers.discard(writer)
            writer.close()
