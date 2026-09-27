# ПроАкт.Транспорт — прогноз задержек городского транспорта за 10–15 минут

Хакатон Московского транспорта 2026, трек «Предиктор изменений в графике транспорта». Система в реальном времени
принимает телеметрию NDTP, сверяет её с расписанием, за **10–15 минут** до прибытия прогнозирует задержку, её
вероятность, интервал и причину и показывает диспетчеру карту бортов с цветом риска, ленту алертов и карточку
инцидента с рекомендацией.

Три модуля в Docker: **ml-core** (CatBoost + PyTorch через ONNX, `:8001`) · **backend** (приём NDTP `:9201`, тик
прогнозов, алерты, REST и WebSocket `:8000`) · **дашборд** (React + MapLibre, nginx `:3000`).

## Развёрнутый стенд

Та же система из `docker compose` работает на сервере, поток — replay реального дня 06.01.2026 по NDTP (×10, по кругу):

| Что открыть | Адрес |
|---|---|
| **Дашборд диспетчера** | http://158.160.13.247:3000 |
| Swagger backend · Swagger ml-core | http://158.160.13.247:8000/docs · http://158.160.13.247:8001/docs |
| Статус потока · горизонт 10–15 мин и онлайн-MAE | http://158.160.13.247:8000/api/v1/system/status · http://158.160.13.247:8000/api/v1/metrics/horizon |
| Документация по коду (pdoc) и OpenAPI | https://lavrentiy123.github.io/proact-transport/ |

Стенд общий: перемотку времени и обрыв потока удобнее проверять на своём запуске по инструкции ниже.

## Быстрый старт (для жюри)

Нужны Docker Desktop / Docker Engine с Compose v2, 8 ГБ ОЗУ и ~4 ГБ на диске. Интернет — только на сборку образов.

```bash
git clone https://github.com/Lavrentiy123/proact-transport.git
cd proact-transport
docker compose up --build -d
```

Первая сборка — несколько минут, повторный запуск — секунды. Готовность: `curl http://localhost:8000/ready`
(ответ `{"status":"ready",…}`). Через несколько секунд начинается поток: по умолчанию воспроизводится реальный день
06.01.2026 из датасета по настоящему бинарному NDTP (старт 07:00, скорость ×10).

| Что открыть | Адрес |
|---|---|
| **Дашборд диспетчера** (карта, риск, алерты, карточка инцидента) | http://localhost:3000 |
| Swagger backend (пробные запросы) | http://localhost:8000/docs |
| Swagger ml-core | http://localhost:8001/docs |
| Горизонт 10–15 мин и онлайн-MAE на потоке | http://localhost:8000/api/v1/metrics/horizon |
| Борта с прогнозом · алерты · статус | `/api/v1/vehicles` · `/api/v1/alerts` · `/api/v1/system/status` на `:8000` |
| Метрики Prometheus (пакеты, CRC, тик и инференс p50/p99) | http://localhost:8000/metrics |

Порт занят — скопируйте `.env.example` в `.env` и поменяйте `FRONTEND_PORT`, `BACKEND_PORT`, `ML_CORE_PORT`.
Официальный эмулятор NDTP: `docker load -i data/ndtp-telemetry-emulator.tar`, затем
`docker compose --profile emulator up -d`. Обрыв потока и восстановление: `bash scripts/chaos.sh`.
Подробная инструкция — **[docs/JURY_GUIDE.md](docs/JURY_GUIDE.md)**. Остановить всё: `docker compose --profile emulator down`.

## Как решение закрывает критерии

| Критерий | Чем подтверждается |
|---|---|
| 1. Точность ML | **скор на сайте 1.00 — верх шкалы** (≥ 0.70 = максимум баллов) с первой попытки; сабмит `submissions/sub_20260926_1522_mds_v1.csv`: MAE 63.0 с на тесте организаторов против 93.4 с у бейзлайна «задержка = текущее отклонение»; честная оценка на незнакомом борту (LOBO) 75.2 с (модели на детекторе v2 — 74.6 с); поток без подсказки организаторов (сабмит из цепочки NDTP → `OnlineVehicle` → ml-core, `src/ml/stream_submission.py`) — official 68.8 с, оценка скора ≈ 0.82 — [`docs/model_card.md`](docs/model_card.md) |
| 2. Горизонт 10–15 мин | прогноз строится только для плановой остановки в окне (T+10, T+15]; на потоке 100 % прогнозов в окне (`/api/v1/metrics/horizon`, журнал `/api/v1/journal.csv`); у прогноза — ожидаемая задержка, интервал q10–q90, P(опоздание) и причина — [`reports/online_eval.md`](reports/online_eval.md) |
| 3. Система в Docker | одна команда `docker compose up --build -d`; ml-core и backend — отдельные сервисы со Swagger; backend парсит NDTP (CRC-16/Modbus), сверяет с расписанием детектором прибытий и считает текущее отклонение, скорость на перегоне и время простоя; поток → прогноз → дашборд — [`docs/architecture.md`](docs/architecture.md) |
| 4. Дашборд | карта бортов с цветом риска, лента алертов по приоритету, карточка инцидента (прогноз, причина с доказательством, участок, рекомендация, «отправить водителю», What-If по скорости), обновление по WebSocket раз в секунду — [`frontend/README.md`](frontend/README.md) |
| 5. Производительность и надёжность | ml-core на батч тика (ансамбль + интервал + причины) p50 27.9 мс, p99 124 мс; тик p50 61 мс при периоде 500 мс; 1 000 юнитов эмулятора без ошибок CRC; обрыв потока → DEGRADED и прогноз по расписанию, возврат → LIVE за 1.8 с; холодный старт до `/ready` 12.8 с — [`docs/perf.md`](docs/perf.md) |

## ML в двух словах

- **Признаки** — один пакет [`features/`](features) для обучения и для потока: 34 признака из телеметрии до момента
  прогноза (скорости, стоянки в зоне остановки и вне её, смещение, дистанция по маршруту) и планового расписания;
  детектор прибытий восстанавливает отклонение на потоке. Онлайн и офлайн совпадают до 1e-6 (тест).
- **Модели** — CatBoost для сабмита; на потоке — ансамбль CatBoost по расписанию + PyTorch MLP (ONNX, onnxruntime)
  с весами, выбранными честной валидацией по бортам (LOBO); квантильные CatBoost для интервала q10–q90 (калиброван
  до 80 %); причина — групповая окклюзия признаков (затор / посадка / накопленное отставание / сложный участок).
- **Честность** — утечку (validate = тот же период, что test, факты лежат в расписании) нашли и не использовали;
  копии бортов откладываются вместе с оригиналом — [`docs/ANTI_LEAKAGE.md`](docs/ANTI_LEAKAGE.md).
- Карточка модели и все метрики — [`docs/model_card.md`](docs/model_card.md), бизнес-эффект —
  [`docs/business_effect.md`](docs/business_effect.md).

## Документация

- Инструкция для жюри — [`docs/JURY_GUIDE.md`](docs/JURY_GUIDE.md); архитектура — [`docs/architecture.md`](docs/architecture.md);
  производительность — [`docs/perf.md`](docs/perf.md); текст для формы — [`docs/form_perf_and_features.md`](docs/form_perf_and_features.md).
- Документация по коду (pdoc): ML — [`docs/api/ml/index.html`](docs/api/ml/index.html) (пакеты `features`, `ml_core`),
  backend — [`docs/api/backend/index.html`](docs/api/backend/index.html); OpenAPI без запуска — `docs/api/backend/openapi.json`.
  Онлайн: https://lavrentiy123.github.io/proact-transport/.
- Контракты между модулями — [`contracts/`](contracts/README.md).
- Внешние данные, сервисы и библиотеки с лицензиями (п. 9.4 Положения) — [`docs/THIRD_PARTY.md`](docs/THIRD_PARTY.md).

## Разработка, обучение и тесты

```bash
python -m venv .venv312 && .venv312/Scripts/python -m pip install -r requirements/ml.txt   # Python 3.12
.venv312/Scripts/python -m pytest -m "not slow"          # быстрые тесты (все модули)
.venv312/Scripts/python -m src.ml.train_models           # переобучение CatBoost (LOBO-выбор, ~45 мин на ноутбуке)
.venv312/Scripts/python -m src.ml.torch_mlp              # PyTorch MLP, ONNX-экспорт, веса ансамбля
.venv312/Scripts/python -m src.ml.predict_submission --model m_ds   # сабмит по validate
.venv312/Scripts/python -m src.eval.online_replay_eval   # онлайн-replay: горизонт и онлайн-MAE
```

Результаты онлайн-оценки — [`reports/online_eval.md`](reports/online_eval.md), замеры производительности —
[`docs/perf.md`](docs/perf.md), сырые логи прогонов — `reports/logs/` и `docs/reports/logs/`.

## Структура репозитория

```text
├── backend/        # FastAPI: NDTP-сервер, replay, тик прогнозов, алерты, REST + WebSocket (Расцов)
├── frontend/       # дашборд диспетчера: React + MapLibre, nginx (Пуртов)
├── ml_core/        # сервис инференса: CatBoost + ONNX, интервал, причины, /v1/predict (Ямпуров)
├── features/       # общий пакет признаков и детектор прибытий — одинаково офлайн и на потоке
├── src/ml/         # обучение и валидация моделей; src/eval/ — онлайн-оценка; src/product/ — материалы питча
├── models/         # обученные модели (.cbm, .onnx), feature_config.json, model_card.json
├── contracts/      # pydantic-контракты между модулями и пример сообщения WebSocket
├── data/           # датасет организаторов (CSV) и образ эмулятора NDTP (Git LFS)
├── docs/           # инструкция для жюри, архитектура, производительность, pdoc, питч
├── submissions/    # сабмиты и журнал загрузок
├── tests/          # pytest: ml, ml_core, backend, product
└── docker-compose.yml
```

## Команда «ПроАкт.Транспорт»

Ямпуров — ML и интеграция (капитан) · Расцов — backend и DevOps · Пуртов — frontend и дашборд.
