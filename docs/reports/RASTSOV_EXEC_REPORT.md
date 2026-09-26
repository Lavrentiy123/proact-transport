# Отчёт о выполнении плана Расцова (backend и DevOps)

План и критерии — `docs/RASTSOV_BRIEF.md`, §6 и §6.1. Ветка `rastsov/backend`. Время — МСК.
Правило: в таблице только проверенное; числа — из вывода команд. Хэш коммита шага дописывается следующим коммитом (в самом коммите он ещё неизвестен).

## 1. Сводка

Заполняется в конце.

## 2. Таблица по шагам

| № | Статус | Коммит | Критерий из брифа (дословно) | Чем проверено (команда) | Результат |
|---|---|---|---|---|---|
| 1 | готово; сообщение Пуртову — нужен человек | `7b9f833` | «`pytest tests/backend` зелёный, каждый ответ проходит `model_validate` по `contracts.schemas`; пуш; Пуртову отправлена команда запуска API» | `.venv/Scripts/python.exe -m pytest tests/backend -q`; `BACKEND_STUB=1 python -m uvicorn backend.app.main:app --port 8000`, затем `curl localhost:8000/ready`, `curl -o /dev/null -w %{http_code} localhost:8000/docs`, клиент `websockets` на `/ws/live` | `9 passed`; `{"status":"ready","detail":"stub: contracts/examples/ws_snapshot.json"}`; `docs:200`; `ws 0 snapshot 2026-01-06T12:40:00 3` / `ws 1 snapshot …`. Команда для Пуртова записана в `backend/README.md`; отправить её в чат команды может только человек |
| 2 | готово | `f0abad7` | «round-trip на 1000 случайных кадров; дамп живого эмулятора разбирается без CRC-ошибок; битый CRC и мусор не роняют парсер» | `.venv/Scripts/python.exe -m pytest tests/backend -W ignore` (тесты `test_round_trip_1000_random_frames`, `test_emulator_fixture_parses_without_crc_errors`, `test_bad_crc_is_counted_not_raised`, `test_garbage_before_signature_resyncs`, `test_stream_split_into_random_chunks`); фикстура записана с живого `ndtp-telemetry-emulator:1.0` | `18 passed in 0.67s`; разбор фикстуры: `20 DecodeStats(frames=20, crc_errors=0, garbage_bytes=0, bad_headers=0, unknown_cells=0) 0`; ячейки realtime `[0, 8, 16, 2, 10]` |
| 3 | готово | этот коммит `[BE-3]` | «живой эмулятор → `/api/v1/system/status`: `ndtp_sessions > 0`, пакеты растут, `crc_errors = 0`, сервис не падает на неизвестном `unitId`» | backend: `python -m uvicorn backend.app.main:app --port 8000` (NDTP :9201); эмулятор: `docker run --rm -p 18080:18080 --add-host=host.docker.internal:host-gateway ndtp-telemetry-emulator:1.0`; `POST /api/config` с юнитами 1166336 и 900001 (`autoGenerate`, `intervalMs: 2000`, в датасете их нет); `curl /api/v1/system/status` через 5 с и ещё через 10 с; `curl /health`; `curl /api/v1/vehicles`. Тест `tests/backend/test_ndtp_ingest.py` (реальный сокет) | t1: `"ndtp_sessions":2 … "ndtp_packets_total":6 … "ndtp_crc_errors_total":0 … "unknown_units":2`; t2 (+10 с): `"ndtp_packets_total":16 … "ndtp_crc_errors_total":0`; `health:200`; `vehicles [(900001, 55.6998, 37.5001, None), (1166336, 55.7338, 37.5333, None)]`; строк `error/traceback` в логе backend: 0; `pytest tests/backend`: `21 passed in 1.12s` |

## 3. Тесты

Заполняется в конце.

## 4. Отклонения от плана

Заполняется по ходу.

## 5. Блокеры и зависимости

Заполняется по ходу.

## 6. Производительность и холодный старт

Заполняется после шагов 6 и 8.

## 7. Что осталось и следующий шаг

Заполняется в конце.

## 8. Как проверить за 5 минут

Заполняется в конце.
