# Инструкция для жюри: ПроАкт.Транспорт

Система из трёх модулей в Docker: **ml-core** (прогноз CatBoost, `:8001`), **backend** (приём NDTP `:9201`, тик прогнозов, алерты, REST и WebSocket `:8000`), **дашборд** (frontend `:3000`, ветка Пуртова). Поток телеметрии — бинарный NDTP: по умолчанию воспроизводится реальный день 06.01.2026 из датасета, по желанию — официальный эмулятор организаторов.

## 1. Что нужно

- Docker Desktop / Docker Engine с Compose v2 (`docker compose version`), 8 ГБ ОЗУ, 4 ГБ на диске под образы.
- Свободные порты `8000`, `8001`, `9201` (и `18080` для эмулятора). Занят порт — скопируйте `.env.example` в `.env` и поменяйте `BACKEND_PORT` / `ML_CORE_PORT` / `NDTP_PORT`.
- Интернет нужен только на сборку образов (зависимости `pip`). В рантайме ничего не скачивается: модели, расписание и телеметрия дня лежат внутри образов.

## 2. Запуск одной командой

```bash
docker compose up --build -d
```

Первая сборка без кэша Docker — около 2 минут, повторный запуск — секунды (замеры — [`docs/perf.md`](perf.md)). Готовность:

```bash
curl http://localhost:8000/ready
```

Ответ `{"status":"ready",...}` — backend загрузил расписание и слушает NDTP. Через несколько секунд сервис `replay` начинает слать поток, режим в статусе становится `LIVE`.

## 3. Где что смотреть

| Что | Адрес |
|---|---|
| Swagger backend (пробные запросы) | http://localhost:8000/docs |
| Статус: режим LIVE/DEGRADED, время симуляции, сессии NDTP, ml-core | http://localhost:8000/api/v1/system/status |
| Борта с прогнозом на 10–15 минут | http://localhost:8000/api/v1/vehicles |
| Алерты (сортировка по приоритету) | http://localhost:8000/api/v1/alerts |
| Горизонт 10–15 мин и онлайн-MAE на потоке | http://localhost:8000/api/v1/metrics/horizon |
| Журнал прогнозов потока (CSV) | http://localhost:8000/api/v1/journal.csv |
| Метрики Prometheus (пакеты, CRC, тик и инференс p50/p99) | http://localhost:8000/metrics |
| Поток WebSocket для дашборда (1 раз в секунду) | `ws://localhost:8000/ws/live` |
| Swagger ml-core | http://localhost:8001/docs |
| Документация по коду (pdoc) | `docs/api/backend/index.html` (сборка: `bash scripts/build_docs.sh`) |

## 4. Как подать поток

**Вариант 1 — replay реального дня (по умолчанию).** Уже работает после `docker compose up --build -d`: сервис `replay` читает `data/test/traffic.csv` и шлёт кадры NDTP (handshake + `G6CellNav00`) на `backend:9201` — тем же путём, что эмулятор. Старт — 07:00 06.01.2026, скорость ×10. Поменять:

```bash
curl -X POST http://localhost:8000/api/v1/replay/control -H "Content-Type: application/json" -d '{"speed": 5, "start_at": "2026-01-06T07:25:00"}'
```

При переносе времени буферы бортов, алерты и журнал начинаются заново (30 минут «разгона» телеметрии отправляются пачкой).

**Вариант 2 — официальный эмулятор NDTP организаторов.**

```bash
docker load -i data/ndtp-telemetry-emulator.tar
docker compose --profile emulator up -d
```

Backend сам настраивает эмулятор через его REST (`POST /api/config`), эмулятор подключается к `backend:9201`. Если файл образа занимает 134 байта — это указатель Git LFS: выполните `git lfs pull` или возьмите `ndtp-telemetry-emulator.tar` из датасета организаторов.

- По умолчанию (`EMULATOR_MODE=auto`) эмулятор шлёт 3 юнита `autoGenerate`: это случайные точки около (55.70, 37.50) без расписания — они видны на карте как борта без прогноза (проверка совместимости протокола). Прогнозы в это время строятся по replay.
- Нагрузка на 1000 юнитов: `EMULATOR_UNITS=1000 EMULATOR_INTERVAL_MS=1000 docker compose --profile emulator up -d` (в PowerShell: `$env:EMULATOR_UNITS=1000; $env:EMULATOR_INTERVAL_MS=1000; docker compose --profile emulator up -d`).
- Реальные треки датасета через официальный эмулятор: `EMULATOR_MODE=trajectories REPLAY_SPEED=2 docker compose --profile emulator up -d --scale replay=0`. Раз в 10 с времени симуляции backend отправляет эмулятору последние фиксы бортов; эмулятор ставит в пакет текущее время, backend переводит его во время симуляции.

## 5. Проверки за минуту

```bash
curl http://localhost:8000/api/v1/system/status
curl http://localhost:8000/api/v1/metrics/horizon
curl http://localhost:8000/api/v1/alerts
bash scripts/chaos.sh
```

- `metrics/horizon`: `share_lead_in_window` — доля прогнозов, выданных за 10–15 минут до планового прибытия (по построению 1.0); `online_mae_model_s` — MAE прогнозов, уже сверенных с фактическим прибытием, которое зафиксировал поток (детектор прибытий, не данные расписания).
- Первый алерт на replay с 07:00 при ×10 появляется примерно через 2.5–3 минуты: модель впервые даёт красный прогноз в 07:27 по времени датасета. Быстрее увидеть алерт: `start_at` = `2026-01-06T07:25:00` (команда выше).
- `scripts/chaos.sh` останавливает источник потока → режим `DEGRADED` (прогноз по расписанию, `quality=fallback`), затем запускает → `LIVE`; то же для `ml-core` (прогноз по правилу). Сервис не падает.

## 6. Если что-то пошло не так

| Симптом | Что сделать |
|---|---|
| `port is already allocated` | `.env` с другими портами (см. §1) |
| `/ready` не отвечает | `docker compose ps`, `docker compose logs backend --tail 50` |
| режим `DEGRADED` сразу после старта | подождать 5–10 с: replay подключается после готовности backend; `docker compose logs replay` |
| `ml_core_ok: false` | `docker compose logs ml-core`; прогнозы при этом идут по правилу с `quality=fallback` |
| `No such image: ndtp-telemetry-emulator:1.0` | `docker load -i data/ndtp-telemetry-emulator.tar` (см. §4) |
| остановить всё | `docker compose --profile emulator down` |
