# Контракты между модулями (v0)

Модели данных: [`schemas.py`](schemas.py). Пример сообщения WebSocket для моков фронта: [`examples/ws_snapshot.json`](examples/ws_snapshot.json).
Правило: новые **необязательные** поля добавлять можно свободно, переименовывать и удалять — только через Ямпурова (интегратор).

## Сервисы и порты (docker-compose)

| Сервис | Порт | Владелец | Что делает |
|---|---|---|---|
| `backend` | 8000 (HTTP/WS), 9201 (NDTP TCP) | Расцов | приём NDTP, состояние бортов, тик прогнозов, алерты, REST + WS |
| `ml-core` | 8001 | Ямпуров | инференс CatBoost (+ PyTorch), причины, `/v1/predict` |
| `frontend` | 3000 (nginx) | Пуртов | дашборд, проксирует `/api` и `/ws` на backend |
| `ndtp-emulator` | 18080 | — | официальный образ, шлёт NDTP на `backend:9201` (профиль `emulator`) |

## REST backend (`/docs` — Swagger)

| Метод | Путь | Ответ | Приоритет |
|---|---|---|---|
| GET | `/health`, `/ready` | 200 / 503 | P0 |
| GET | `/api/v1/system/status` | `SystemStatus` | P0 |
| GET | `/api/v1/vehicles` | `list[VehicleState]` | P0 |
| GET | `/api/v1/alerts?status=active` | `list[Alert]`, сортировка по `priority` | P0 |
| GET | `/api/v1/tracks/{tr_id}` | `TrackResponse` (линия на карте + Марей) | P0 |
| POST | `/api/v1/actions` | `ActionRequest` → `ActionResponse` | P1 |
| GET | `/api/v1/metrics/horizon` | `HorizonMetrics` | P1 |
| POST | `/api/v1/what-if` | `WhatIfRequest` → `WhatIfResponse` | P2 |
| POST | `/api/v1/replay/control` | `{"speed": 5, "start_at": "2026-01-06T07:00:00"}` | P1 |
| GET | `/metrics` | Prometheus-текст: pkt/s, crc_errors, tick_ms p50/p99, infer_ms | P1 |
| WS | `/ws/live` | `WsMessage` раз в 1 с (`type=snapshot`) | P0 |

## ml-core

| Метод | Путь | Тело |
|---|---|---|
| GET | `/health` | — |
| GET | `/v1/model` | версия, список признаков, метрики LOBO |
| POST | `/v1/predict` | `PredictRequest` → `PredictResponse` (батч на все борта за один вызов) |

## Пакет признаков `features/` (владелец — Ямпуров)

Одна функция для обучения и для потока, иначе прогноз на потоке разойдётся с офлайн-метриками:

Для backend главное — `OnlineVehicle`: буфер 30 мин + детектор прибытий + те же признаки, что при обучении
(совпадение онлайн/офлайн проверяет `tests/ml/test_online_parity.py`, допуск 1e-6).

```python
from features import OnlineVehicle, load_schedule, features_to_json

sched = load_schedule("data/test/schedule.csv")          # tr_id, stop_id, time_plan, lat, lon, name
veh = {tr: OnlineVehicle(rows, tr_id=tr) for tr, rows in sched.groupby("tr_id")}

veh[tr].push(t, lat, lon, speed, heading, valid)          # на каждый NDTP-пакет (можно не по порядку)
tgt = veh[tr].target_at(now)                              # (stop_id, time_plan) в окне (now+10, now+15] или None
feats = veh[tr].features_at(now)                          # dict FEATURE_NAMES или None (нет остановки в окне)
row = {"tr_id": tr, "features": features_to_json(feats)}  # NaN -> None для PredictRow
veh[tr].derived(now)            # {"cur_dev_s", "seg_speed_kmh", "dwell_s"} для VehicleState
veh[tr].is_opening_or_closing_trip(now), veh[tr].stop_name(stop_id), veh[tr].detector.arrivals
```

Низкоуровневое API (обучение, тесты):

```python
from features import FEATURE_NAMES, build_features, build_features_batch, StopDetector

det = StopDetector(schedule_rows_for_tr)   # плановые остановки борта
det.update(t, lat, lon, speed)             # на каждый пакет; фиксирует прибытия
det.cur_dev_s(T)                           # отклонение на последней пройденной к T остановке (NaN, если нет)

feats: dict[str, float] = build_features(
    track=track,                  # DataFrame[t, lat, lon, speed, heading, valid]; строки t > T игнорируются
    schedule=schedule_rows_for_tr,
    target_stop_id=..., target_time_plan=..., T=...,
    cur_dev_s=None,               # None — восстановленное детектором (как на потоке)
    arrivals=det,                 # необязательно: StopDetector / dict / None (детектор внутри)
)
```

## Логика тика backend (каждые 5 с времени симуляции)

1. Для каждого активного борта найти первую плановую остановку с `time_plan ∈ (now+10 мин, now+15 мин]`. Нет такой — прогноз не строим.
2. `build_features(...)` → один батч `POST ml-core /v1/predict`.
3. `risk`: green < 120 с ≤ yellow < 300 с ≤ red (или `p_late ≥ 0.8`). Алерт поднимается на red, снимается, когда прогноз < 200 с два тика подряд.
4. Рекомендация по правилам: опаздывает → `speed_advice` (скорость = оставшаяся дистанция / оставшееся плановое время); опережает → `hold` (межрейсовая стоянка, 30–120 с); red на первом или последнем рейсе → `reserve`.
5. Каждый прогноз пишется в журнал (`issued_at, tr_id, stop, lead_s, pred`). Когда детектор фиксирует прибытие, дописывается факт — отсюда `HorizonMetrics`.
