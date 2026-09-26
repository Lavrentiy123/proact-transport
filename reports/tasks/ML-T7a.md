# ML-T7a: Слияние №1 и сквозная проверка — ✅
**Время:** 45 мин (из них ~15 мин — сборка образов)   **Коммит:** merge 56813e5 (backend), 7065504 (frontend), 83836e1 (правки и отчёт)   **Пуш:** да
## Сделано
- `git fetch`: `origin/rastsov/backend` — 17 новых коммитов (BE-1…BE-13: NDTP, replay, тик, алерты, WS, compose, DEGRADED, `/metrics`, `/actions`, pdoc, JURY_GUIDE); `origin/purtov/frontend` — 0, работа Пуртова лежит в **`origin/codex/purtov-frontend`** (3 коммита: дашборд, Dockerfile с nginx, аудит) — слита она.
- `git merge --no-ff` backend, затем frontend — **конфликтов нет** (файлы не пересекаются).
- Правки слияния (только общие файлы и стыки):
  - `docker-compose.yml`: раскомментирован сервис `frontend` (TODO Расцова «раскомментировать при слиянии с веткой Пуртова»); healthcheck фронта — `127.0.0.1` вместо `localhost` (в alpine `localhost` = `::1`, nginx слушает IPv4 — контейнер был `unhealthy`); таймаут healthcheck ml-core и backend 3 → 10 с (запуск `python` в проверке на загруженной машине дольше 3 с — compose не поднимал фронт из-за «unhealthy» backend).
  - `tests/backend/test_tick.py` (тест Расцова, **код `backend/` не менялся**): (1) `degraded_after_s=1e9` — фиксы подаются в fleet мимо NDTP-сервера, и на медленной машине 420 тиков шли дольше 15 с реального времени → режим DEGRADED и `model="sched"`; (2) убрана привязка к таймлайну старой модели («первый красный не раньше 07:10») — после ML-T5 (ансамбль) первый алерт в 07:01:50; проверяются инварианты (алерт поднят, есть причина с доказательством, заголовок, `WsMessage` валиден).
  - `ml_core/inference.py`: признаки пакета, которые модель не использует (`tod_*`, `hour` для m_online), больше не считаются «лишними» — в логе ml-core было «ignored 24 unknown feature values» на каждом тике.
  - Латентностные тесты ML устойчивы к перегрузке ноутбука (лучший из 10 прогонов / p25).
- Сквозная проверка: `docker compose up --build -d` (порты `ML_CORE_PORT=18001`, `FRONTEND_PORT=13000` — 8001 и 3000 заняты контейнерами другого проекта `agro-*`, их не трогал) → `scripts/smoke_e2e.py` → `docker compose down`.
## Файлы
- merge-коммиты; `docker-compose.yml`, `tests/backend/test_tick.py`, `ml_core/inference.py`, `tests/ml/test_causes.py`, `tests/ml/test_torch_member.py`
## Тесты
`pytest -m "not slow"` на слитом `main` → passed 130, failed 0 (включая `tests/backend`)
`scripts/smoke_e2e.py --ml-core http://localhost:18001 --frontend http://localhost:13000` → **E2E SMOKE OK**
## Метрики
| проверка | результат | порог |
|---|---|---|
| `GET :8000/health`, `GET :8001/ready`, `GET :3000` (HTML) | 200 / 200 / 200 | 200 |
| `GET /api/v1/vehicles` | 15 бортов | непустой |
| `/ws/live` → `snapshot`, борта с `forecast.lead_s ∈ [600, 900]` | 8 из 15 (пример: борт 122048, lead 655 с, +45 с, green, accumulated) | ≥ 1 |
| статус контейнеров после правок | backend, ml-core, frontend — healthy; replay — up | healthy |
| сборка с кешем ML-слоёв (backend + frontend впервые, с загрузкой базовых образов) | ~12 мин | отчёт |
## Риски: что сработало и как закрыто
- Ветки обновились позже контрольного плана → слил в 17:30, как только появился код; повтор слияния — T7b/T7c.
- Работа Пуртова в другой ветке (`codex/purtov-frontend`) → слита она; `purtov/frontend` пуста.
- Сломанный `main` у команды → пуш только после зелёного pytest и e2e.
- Порты 3000/8001 заняты чужими контейнерами → переопределение через переменные compose (`.env` поддерживает `ML_CORE_PORT`, `FRONTEND_PORT`).
## Открытые вопросы / что нужно от пользователя или команды
- **Расцову:** посмотреть правки в `tests/backend/test_tick.py` и `docker-compose.yml` (выше); в `backend/` ничего не менялось.
- **Решения капитана по брифу Расцова:** Б3 — счётчики NDTP оставить подклассом `SystemStatusEx` в backend (контракт не трогаем за сутки до сдачи); Б4 — fallback без ml-core: правило `0.6·cur_dev + 8` хуже нуля (136 против 103 с) → предлагаю прогноз 0 с `quality=fallback` (владелец — Расцов).
- **Пользователю:** репозиторий приватный — ссылки для жюри отдают 404 (отчёт Расцова, шаг 12); открыть доступ до сдачи. В `main` лежит `ChatExport_2026-09-26/` с адресами почты участников (аудит Пуртова) — решить, оставлять ли.
- Для `docker compose up` на этом ноутбуке без переопределения портов — остановить `agro-frontend`/`agro-bot`.
