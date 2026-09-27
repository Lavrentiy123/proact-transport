"""WebSocket ``/ws/live``: снапшот ``WsMessage`` раз в секунду.

Один производитель считает снапшот раз в период и раскладывает JSON по очередям клиентов.
У каждого клиента очередь на 1 сообщение: новый снапшот вытесняет старый, поэтому медленный
клиент не тормозит остальных (вытеснения считаются в ``dropped``).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

log = logging.getLogger("backend.ws")
router = APIRouter()


class Broadcaster:
    """Раздаёт снапшоты подключённым клиентам.

    Args:
        make_json: функция без аргументов, возвращающая JSON-строку снапшота.
        period_s: период рассылки, секунды.
    """

    def __init__(self, make_json, period_s: float = 1.0):
        self.make_json = make_json
        self.period_s = period_s
        self.clients: set[asyncio.Queue] = set()
        self.dropped = 0
        self.sent = 0
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="ws-broadcaster")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    def publish(self, payload: str) -> None:
        for q in list(self.clients):
            if q.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    q.get_nowait()
                self.dropped += 1
            q.put_nowait(payload)

    async def _run(self) -> None:
        while True:
            if self.clients:
                try:
                    self.publish(self.make_json())
                except Exception:  # снапшот не должен ронять рассылку
                    log.exception("snapshot failed")
            await asyncio.sleep(self.period_s)


@router.websocket("/ws/live")
async def ws_live(ws: WebSocket) -> None:
    """Отправляет ``WsMessage`` (``type=snapshot``) раз в секунду; первый — сразу после подключения."""
    await ws.accept()
    b: Broadcaster = ws.app.state.broadcaster
    q: asyncio.Queue = asyncio.Queue(maxsize=1)
    b.clients.add(q)
    try:
        await ws.send_text(b.make_json())
        while True:
            payload = await q.get()
            await ws.send_text(payload)
            b.sent += 1
    except WebSocketDisconnect:
        pass
    except Exception as e:  # обрыв на отправке: у разных серверов разные исключения
        log.info("ws client closed: %s: %s", type(e).__name__, e)
    finally:
        b.clients.discard(q)
