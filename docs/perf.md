# Производительность и надёжность: замеры

Стенд: ноутбук команды, 8 логических ядер, 32 ГБ ОЗУ, Windows 11, Docker Desktop 28.5 (Linux-контейнеры). Все числа — из вывода команд ниже (`scripts/measure_perf.py` печатает JSON-строку на каждую цифру), не оценки. Поток — replay дня 06.01.2026 с 07:00, скорость ×10: 13 бортов с расписанием, до 16 терминалов в эфире.

## Холодный старт и сборка

| Цифра | Значение | Команда воспроизведения |
|---|---|---|
| Сборка всех образов без кэша Docker | 121 с | `docker compose build --no-cache` (замер шага 6, чистый клон) |
| `docker compose up -d` (образы собраны, контейнеры удалены) | 12.8 с | `python scripts/measure_perf.py cold` |
| От `up -d` до `/ready` = 200 | 12.8 с | `python scripts/measure_perf.py cold` |
| От `up -d` до первого борта с прогнозом | 15.0 с | `python scripts/measure_perf.py cold` |
| От `up -d` до первого алерта | 169.4 с | `python scripts/measure_perf.py cold` — модель впервые даёт красный прогноз в 07:27 времени датасета; с `start_at` 07:25 алерт появится в первые секунды |
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
| WebSocket: период / размер снапшота | 1.0 с / 8 049 байт | то же |

## Парсер NDTP

| Цифра | Значение | Команда |
|---|---|---|
| Кадров Nav00 в секунду, один поток | 110 851 | `python scripts/measure_perf.py codec` |
| Микросекунд на кадр | 9.02 | то же |

## Нагрузка официальным эмулятором

Замер — шаг 9 плана (1000 юнитов эмулятора); таблица дописывается после него.

## Надёжность (chaos-тест)

| Сценарий | Результат | Команда |
|---|---|---|
| Обрыв потока → DEGRADED | 14.7 с после остановки источника; `/health` 200; прогнозы `quality=fallback` (m_sched) | `bash scripts/chaos.sh` |
| Поток вернулся → LIVE | 1.8 с после запуска источника | то же |
| ml-core остановлен → прогноз по правилу | 0.2 с; `/health` 200 | то же |
| ml-core запущен → снова ml-core | 31.3 с (circuit breaker открыт 30 с) | то же |
| Остановка replay (`docker compose stop replay`) | 0.8 с (SIGTERM обрабатывается) | `docker compose stop replay` |

## Как читать метрики на живой системе

`curl http://localhost:8000/metrics` — `tick_duration_ms{quantile}`, `infer_ms{quantile}` (последние 2000 тиков), `ndtp_packets_total`, `ndtp_crc_errors_total`, `dropped_total{kind}`, `online_mae_seconds{model}`, `horizon_share_in_window`.
