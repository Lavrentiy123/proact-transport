# backend

FastAPI-сервис: приём NDTP, состояние бортов, тик прогнозов, алерты, REST и WebSocket.
Контракт ответов — [`contracts/schemas.py`](../contracts/schemas.py), список эндпоинтов — [`contracts/README.md`](../contracts/README.md).

## Запуск для фронта на заглушке (без потока и модели)

Из корня репозитория, Python 3.12:

```bash
pip install -r backend/requirements.txt
BACKEND_STUB=1 python -m uvicorn backend.app.main:app --port 8000
```

PowerShell: `$env:BACKEND_STUB="1"; python -m uvicorn backend.app.main:app --port 8000`.

- Swagger: http://localhost:8000/docs
- WebSocket: `ws://localhost:8000/ws/live` — `WsMessage` раз в секунду.
- Заглушка отдаёт `contracts/examples/ws_snapshot.json` и плановые остановки из `data/test/schedule.csv`. Это **не** живые данные.

## Тесты

```bash
pip install -r backend/requirements-dev.txt
python -m pytest tests/backend
```
