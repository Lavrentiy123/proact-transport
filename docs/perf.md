# Производительность и надёжность: замеры

Стенд: ноутбук команды, 8 логических ядер, 32 ГБ ОЗУ, Windows 11, Docker Desktop 28.5 (Linux-контейнеры). Все числа — из вывода команд ниже (`scripts/measure_perf.py` печатает JSON-строку на каждую цифру), не оценки. Поток — replay дня 06.01.2026 с 07:00, скорость ×10: 13 бортов с расписанием, до 16 терминалов в эфире.

## Холодный старт и сборка

| Цифра | Значение | Команда воспроизведения |
|---|---|---|
| Сборка всех образов без кэша Docker | 121 с | `docker compose build --no-cache` (замер шага 6, чистый клон) |
| `docker compose up -d` (образы собраны, контейнеры удалены) | 12.8 с | `python scripts/measure_perf.py cold` |
| От `up -d` до `/ready` = 200 | 12.8 с | `python scripts/measure_perf.py cold` |
| От `up -d` до первого борта с прогнозом | 15.0 с | `python scripts/measure_perf.py cold` |
| От `up -d` до первого алерта | 169.4 с до вливания ML-T5; **20.3 с** после вливания `origin/main` (ансамбль ml-core с PyTorch/ONNX, лог `docs/reports/logs/step5_after_main_merge.txt`) | `python scripts/measure_perf.py cold` — модель впервые даёт красный прогноз в 07:27 времени датасета; с `start_at` 07:25 алерт появился через 11 с при ×10 (шаг 10) и 20 с при ×5 (шаг 13); повтор после исправлений: 157.5 с после `up -d` (`docs/reports/logs/step5_first_alert.txt`) |
| Размеры образов | ml-core 1.15 ГБ, backend 468 МБ | `docker images | grep proact` |

## Поток и тик (replay ×10, 10 минут)

| Цифра | Значение | Команда воспроизведения |
|---|---|---|
| Пакетов NDTP в секунду (replay ×10) | 13.9 | `python scripts/measure_perf.py load --minutes 10` (разница `ndtp_packets_total` за 600 с) |
| Тик прогнозов p50 / p99 (признаки + ml-core + алерты, 9 бортов с целью в окне) | 13.1 / 24.9 мс | то же (`tick_duration_ms`, последние 2000 тиков; период тика 5 с симуляции = 0.5 с реального времени) |
| Вызов ml-core `/v1/predict` на батч тика p50 / p99 (HTTP) | 7.6 / 13.5 мс | то же (`infer_ms`) |
| Тиков, не уложившихся в период / с ошибкой | 0 / 0 | то же (`tick_overruns_total`, `tick_errors_total`) |
| Ошибок CRC / пакетов старше буфера | 0 / 0 | то же |
| Доля прогнозов с горизонтом 10–15 мин | 1.0 | то же (`horizon_share_in_window`) |
| Онлайн-MAE прогноза / бейзлайна «задержка = cur_dev» (по всем прогнозам тиков, 9684 сверены с прибытием из детектора) | 85.3 / 173.7 с | то же (`online_mae_seconds`) |
| `GET /api/v1/vehicles` p50 / p99 | 23.2 / 47.0 мс | то же (587 запросов, раз в секунду) |
| WebSocket: период / размер снапшота | 1.0 с / 8 049 байт | то же (оценка периода тогда включала первое, немедленное сообщение; после исправления скрипта — 0.96 с) |

## Парсер NDTP

| Цифра | Значение | Команда |
|---|---|---|
| Кадров Nav00 в секунду, один поток | 110 851 | `python scripts/measure_perf.py codec` |
| Микросекунд на кадр | 9.02 | то же |

## Нагрузка официальным эмулятором

Команда: `EMULATOR_UNITS=1000 EMULATOR_INTERVAL_MS=1000 docker compose --profile emulator up -d` (backend сам шлёт эмулятору конфиг на 1000 юнитов `autoGenerate`, 1 пакет/с каждый; replay ×10 продолжает идти), через 40 с — `python scripts/measure_perf.py load --minutes 3` и `docker stats --no-stream`.

| Цифра | Значение |
|---|---|
| TCP-сессий NDTP | 1016 (1000 эмулятор + 16 replay) |
| Пакетов в секунду | 1013.7 (разница `ndtp_packets_total` за 180 с) |
| Ошибок CRC | 0 |
| Тик p50 / p99 | 12.5 / 26.9 мс; перегрузок тика 0 |
| ml-core на батч p50 / p99 | 7.2 / 17.9 мс |
| `GET /api/v1/vehicles` p50 / p99 (1016 бортов в ответе) | 35.0 / 112.1 мс |
| Снапшот WebSocket | 228 476 байт, период 0.84 с |
| CPU / память контейнеров | backend 9.9 % / 110 МБ; эмулятор 18.1 % / 817 МБ; ml-core 4.3 % / 97 МБ; replay 1.1 % / 66 МБ |

Режим реальных треков через официальный эмулятор: `EMULATOR_MODE=trajectories REPLAY_SPEED=2 docker compose --profile emulator up -d --scale replay=0` — через 60 с эмулятор настроен на 15 терминалов датасета (формат `"fields"`), прогноз есть у 9 бортов (`quality=full`, ml-core), 0 ошибок CRC.

## Надёжность (chaos-тест)

| Сценарий | Результат | Команда |
|---|---|---|
| Обрыв потока → DEGRADED | 14.7 с после остановки источника; `/health` 200; прогнозы `quality=fallback` (m_sched). Точки отсчёта (повтор после исправлений): 14.6 с от конца `stop`, 15.1 с от последнего пакета, 15.3 с от начала команды `stop` | `bash scripts/chaos.sh`, `python scripts/verify_stream.py degraded` |
| Поток вернулся → LIVE | 1.8 с после запуска источника | то же |
| ml-core остановлен → прогноз по правилу | 0.2 с; `/health` 200 | то же |
| ml-core запущен → снова ml-core | 31.3 с (circuit breaker открыт 30 с) | то же |
| Остановка replay (`docker compose stop replay`) | 0.8 с (SIGTERM обрабатывается) | `docker compose stop replay` |

## Как читать метрики на живой системе

`curl http://localhost:8000/metrics` — `tick_duration_ms{quantile}`, `infer_ms{quantile}` (последние 2000 тиков), `ndtp_packets_total`, `ndtp_crc_errors_total`, `dropped_total{kind}`, `online_mae_seconds{model}`, `horizon_share_in_window`.

## Повтор после исправлений по ревью (коммит `483dced`)

`python scripts/measure_perf.py load --minutes 2`, сразу после chaos-теста — в окно квантилей (последние 2000 тиков) попали тики с остановленным ml-core, поэтому p99 выше, чем в 10-минутном прогоне: тик p50 / p99 14.3 / 35.8 мс, ml-core 8.2 / 23.0 мс, перегрузок тика 2 (во время остановки ml-core), ошибок 0, CRC 0; `GET /api/v1/vehicles` 21.6 / 43.8 мс; WS 0.96 с. Сырой вывод — `docs/reports/logs/after_fix_load2min.jsonl`.
