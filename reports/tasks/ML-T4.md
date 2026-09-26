# ML-T4: Сервис `ml-core` — ✅
**Время:** 35 мин   **Коммит:** см. ML-T7a.md / `git log --grep "ML-T4"`   **Пуш:** см. ML-T7a.md
## Сделано
- `ml_core/app/main.py` (FastAPI): `GET /health`, `GET /ready` (200/503), `GET /v1/model` (версия, признаки, веса ансамбля, метрики из `model_card.json`), `POST /v1/predict` (`PredictRequest` → `PredictResponse` из `contracts/schemas.py`), Swagger на `/docs`. Модели грузятся при старте (lifespan), а не при импорте.
- `ml_core/app/predictor.py`: `online` — m_online + q10/q90 (калибровка ширины по LOBO) + `p_late` + причины окклюзией; `sched` — m_sched, интервал по LOBO MAE (приближение Лапласа), причина `accumulated`/`low_data`. Отсутствующий признак → NaN, лишние игнорируются (число — в лог). `delta_pred_s` — относительно `cur_dev_s` (контракт: `delay = clip(cur_dev + delta)`), модели грузятся из байтов (устойчиво к кириллице в путях).
- `ml_core/Dockerfile` (контекст — корень, `python:3.12-slim`, пользователь `app`, HEALTHCHECK по `/ready`), `ml_core/Dockerfile.dockerignore` (только для этого Dockerfile — не мешает сборкам Расцова и Пуртова), `ml_core/requirements.txt` + `requirements-nodeps.txt` (catboost без plotly/matplotlib/graphviz: −200 МБ).
- `scripts/smoke_ml_core.sh [порт]`: build → run → `/ready` ≤ 60 с → `/v1/predict` на 2 строках → удаление контейнера.
- Общие фикстуры тестов перенесены в `tests/conftest.py` (нужны и `tests/ml_core`).
## Файлы
- `ml_core/app/{__init__,main,predictor}.py`, `ml_core/Dockerfile`, `ml_core/Dockerfile.dockerignore`, `ml_core/requirements.txt`, `ml_core/requirements-nodeps.txt`
- `scripts/smoke_ml_core.sh`, `tests/ml_core/test_api.py`, `tests/conftest.py`
## Тесты
`pytest tests/ml_core/test_api.py` → passed 6, failed 0
`bash scripts/smoke_ml_core.sh 18001` → SMOKE OK
`pytest -m "not slow"` → passed 69, failed 0
## Метрики
| метрика | значение | порог приёмки |
|---|---|---|
| `/v1/predict`, 30 строк (с причинами и интервалом), медиана | **9.7 мс** | < 100 мс |
| холодный старт контейнера до `/ready` | **14 с** | < 30 с |
| размер образа | **1083 МБ** | < 1.2 ГБ |
| пустой батч / кривое тело | 200 / 422 | 200 / 422 |
## Фрагмент compose для Расцова
```yaml
  ml-core:
    build: {context: ., dockerfile: ml_core/Dockerfile}
    ports: ["8001:8001"]
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8001/ready').status==200 else 1)"]
      interval: 10s
      timeout: 3s
      retries: 5
```
Backend зовёт `http://ml-core:8001/v1/predict` одним батчем на тик; `model="sched"` — fallback, когда телеметрии нет.
## Риски: что сработало и как закрыто
- **Порт 8001 на этом ноутбуке занят контейнером `agro-bot` другого проекта** (а 3000 — `agro-frontend`) → smoke прогнан на `-p 18001:8001`; чужие контейнеры не трогал. Для `docker compose up` на этом ноутбуке их нужно остановить (решение за пользователем).
- Образ раздувался зависимостями catboost (plotly, matplotlib, fontTools, pillow) — 1292 МБ → catboost без зависимостей + явные numpy/pandas/scipy/six → 1083 МБ; инференс проверен в контейнере.
- pdoc/тесты импортируют пакет без моделей → загрузка в lifespan; без моделей `/health` 200, `/ready` 503 (проверено).
## Открытые вопросы / что нужно от пользователя или команды
- Расцову: вставить фрагмент compose; в тике слать `features_to_json(veh.features_at(now))`.
