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
| 3 | готово | `214af22` | «живой эмулятор → `/api/v1/system/status`: `ndtp_sessions > 0`, пакеты растут, `crc_errors = 0`, сервис не падает на неизвестном `unitId`» | backend: `python -m uvicorn backend.app.main:app --port 8000` (NDTP :9201); эмулятор: `docker run --rm -p 18080:18080 --add-host=host.docker.internal:host-gateway ndtp-telemetry-emulator:1.0`; `POST /api/config` с юнитами 1166336 и 900001 (`autoGenerate`, `intervalMs: 2000`, в датасете их нет); `curl /api/v1/system/status` через 5 с и ещё через 10 с; `curl /health`; `curl /api/v1/vehicles`. Тест `tests/backend/test_ndtp_ingest.py` (реальный сокет) | t1: `"ndtp_sessions":2 … "ndtp_packets_total":6 … "ndtp_crc_errors_total":0 … "unknown_units":2`; t2 (+10 с): `"ndtp_packets_total":16 … "ndtp_crc_errors_total":0`; `health:200`; `vehicles [(900001, 55.6998, 37.5001, None), (1166336, 55.7338, 37.5333, None)]`; строк `error/traceback` в логе backend: 0; `pytest tests/backend`: `21 passed in 1.12s` |
| 4 | WIP (критерий «30 бортов» недостижим по данным; остальное выполнено) | `11da66d` | «replay ×10 → `/api/v1/vehicles` отдаёт 30 бортов, координаты меняются, `sim_time` идёт» | backend `python -m uvicorn backend.app.main:app --port 8000`; replay отдельным процессом `python -m backend.app.replay --host 127.0.0.1 --port 9201 --sync-url http://127.0.0.1:8000` (скорость ×10 и старт 07:00 — у backend); два среза `curl /api/v1/vehicles` и `/api/v1/system/status` с интервалом 5 с; сверка с CSV по моменту получения (`load_rows`); тест `tests/backend/test_replay.py` (×20, 30 с симуляции, координаты = CSV) | t1: `sim 07:01:06 sessions 16 packets 2837 vehicles 15`; t2: `sim 07:01:58 sessions 16 packets 2932 vehicles 15 moved 8 mode LIVE crc 0`; по данным в окне потока: `units sending in window: 16 \| with valid fix: 15` — API показывает все 15. **Почему не 30:** в `data/test/traffic.csv` 30 терминалов, у 7 за сутки нет ни одного достоверного фикса, около 07:00 в эфире 16; у борта 130576 утренние фиксы пришли на сервер только в 17:18 (`receive_time`). Контракт требует `lat/lon` у каждого борта, выдумывать координаты нельзя. Две проверки (по `event_time`: 16 бортов; по `receive_time`: 15) — API совпадает с данными; `pytest tests/backend`: `25 passed` |
| 5 | WIP (часть «алерт за 60 с» не выполнена: модель m_online даёт первый красный прогноз в 07:27; остальное выполнено) | этот коммит `[BE-5][WIP]` | «replay ×10 с 07:00: за 60 с появляется ≥ 1 алерт; `share_lead_in_window = 1.0`; WS отдаёт настоящий `WsMessage`» | `python -m uvicorn ml_core.app.main:app --port 8001`; `ML_URL=http://127.0.0.1:8001 python -m uvicorn backend.app.main:app --port 8000`; `python -m backend.app.replay --host 127.0.0.1 --port 9201 --sync-url http://127.0.0.1:8000`; скрипт опроса `/api/v1/alerts?status=all` раз в 1 с от старта backend, затем `/api/v1/metrics/horizon`, клиент `websockets` + `WsMessage.model_validate_json`. Офлайн: `tests/backend/test_tick.py` (тик 5 с по телеметрии test-дня, настоящий ml-core через ASGI) | Живой прогон: `FIRST ALERT: wall_s_since_backend_start=162.7 created_at(sim)=2026-01-06T07:26:45 … quality=full model=m_online-v1-7c6e169`; `horizon: forecasts_total 2960, share_lead_in_window 1.0, resolved_total 1358`; `WS: type=snapshot … vehicles=15 with_forecast=9 alerts=1 mode=LIVE`; статус `ml_core_ok True, predictor ml-core, crc 0`. Попытка 1 (офлайн, тики 07:00–07:10 с шагом 5 с): 0 алертов; прогон дня 05:30–20:00: красные прогнозы есть в 07, 12, 13, 17–19 ч, первый алерт 07:27. Причина — модель, а не backend: онлайн-MAE по дню 84.2 с (бейзлайн восстановленного cur_dev 160.1 с) на 9760 сверенных прогнозах совпадает с LOBO m_online 83.0 с. `pytest tests/backend`: `36 passed` |

## 3. Тесты

Заполняется в конце.

## 4. Отклонения от плана

| # | Что | Почему | Чем заменено / как сделано |
|---|---|---|---|
| О1 | Статус расширен необязательными счётчиками NDTP (`ndtp_packets_total`, `ndtp_crc_errors_total` и др.) | Критерий шага 3 требует видеть пакеты и CRC в `/api/v1/system/status`, а в `SystemStatus` таких полей нет; `contracts/` менять запрещено | Подкласс `SystemStatusEx(SystemStatus)` в `backend/app/hub.py`: только новые необязательные поля (правило `contracts/README.md`), контракт не тронут. Внести поля в контракт — вопрос капитану (блокер Б3) |
| О2 | Значение `Mode.replay` не используется | Критерий шага 7 ждёт после восстановления именно LIVE, а наш replay идёт по NDTP тем же путём, что эмулятор | `LIVE` — NDTP-пакеты приходят (любой источник), `DEGRADED` — нет пакетов > 15 с реального времени. Что это replay, видно по `replay_speed` и `sim_time` |
| О3 | Replay шлёт пакет в момент `receive_time`, а не `event_time` | Так пакеты приходят в том порядке и с той задержкой, что у организаторов (буферизованные `is_hist_data` — позже) | `backend/app/replay.py`, момент отправки = `max(event_time, receive_time)`; метка в пакете — `event_time` |
| О4 | Backend отбрасывает пакеты вне окна «сейчас − 40 мин … сейчас + 60 с» | Защита от «будущего» в буфере и от мусорных меток; буфер `OnlineVehicle` всё равно 35 мин | Счётчик `ndtp_dropped_out_of_window` в статусе; тест `test_future_and_ancient_packets_are_dropped` |
| О5 | Добавлен эндпоинт `GET /api/v1/journal.csv` | Шаг 5 п. 8 брифа: выгрузка журнала для «сабмита из потока» | Колонка `sample_id` = `{tr_id}_{T}` как в `validate/points.csv`; факт — из детектора прибытий, не из расписания |
| О6 | Алерт снимается и тогда, когда прогноза нет два тика подряд | У борта может пропасть остановка в окне 10–15 мин (конец рейса) — держать устаревший алерт нельзя | `AlertBook.update`, тест `test_alert_hysteresis_keyed_by_tr` |
| О7 | `last_seen_s` и `stale` считаются в секундах симуляции, DEGRADED — в секундах реального времени | При replay ×10 «30 с молчания борта» — это время датасета, а обрыв потока — реальное время | `backend/app/live.py` |
| О8 | Шаг 4: на карте 15 бортов, а не 30 | В данных нет координат у 7 из 30 терминалов, около 07:00 в эфире 16 терминалов (подробно — строка 4 таблицы) | Показываем все борта с достоверными координатами; критерий не выполнен, шаг помечен WIP |
| О9 | Шаг 5: первый алерт через 162.7 с, а не за 60 с | Модель m_online на test-дне впервые даёт красный прогноз в 07:27 | Шаг помечен WIP; backend не менялся ради критерия |
| О10 | Fallback-правило `0.6·cur_dev + 8` оставлено как в брифе | На восстановленном `cur_dev` оно даёт MAE 136.1 с на `labels_test` (нулевой прогноз — 103.3 с) | Работает только при недоступном `ml-core`, `quality=fallback`, интервал — Лаплас по MAE 136.1 с; при DEGRADED с живым `ml-core` зовётся `model="sched"` (m_sched, LOBO 81.5 с) |

## 5. Блокеры и зависимости

| # | Что нужно | От кого | К какому шагу |
|---|---|---|---|
| Б1 | Решение по критериям шагов 4 и 5: «30 бортов» недостижимо по данным (15–16 около 07:00), «алерт за 60 с с 07:00» недостижимо с m_online (первый красный — 07:27). Варианты: принять фактические цифры или сменить старт демо на 07:25 | Расцов | 4, 5 |
| Б2 | Если для демо нужен алерт в первую минуту — либо старт replay 07:25, либо решение по порогам/калибровке `p_late` модели | капитан | 5, видео |
| Б3 | Внести счётчики NDTP в `SystemStatus` контракта (необязательные поля) или оставить подкласс в backend | капитан (владелец `contracts/`) | 3 |
| Б4 | Fallback-правило из брифа хуже нулевого прогноза на восстановленном `cur_dev`; предложение: без `ml-core` прогнозировать 0 или брать `m_sched` локально | Расцов + капитан | 5, 7 |
| Б5 | Отправить Пуртову команду запуска API (`backend/README.md`) и договориться о портах | Расцов (человек) | 1 |

## 6. Производительность и холодный старт

Заполняется после шагов 6 и 8.

## 7. Что осталось и следующий шаг

Заполняется в конце.

## 8. Как проверить за 5 минут

Заполняется в конце.
