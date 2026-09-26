# ML-T2: Пакет `features/` — одинаковые признаки офлайн и онлайн — ✅
**Время:** 55 мин   **Коммит:** 7c6e169   **Пуш:** да
## Сделано
- `features/`: `geo.py` (haversine R = 6 371 000 м, `parse_point`), `io.py` (`load_traffic`, `load_schedule` без фактов, `ScheduleArrays`, время = наивное время как UTC), `stop_detector.py` (`StopDetector`), `build.py` (`FEATURE_NAMES` — 34 признака, `FEATURES_VERSION = "v1"`, `build_features`, `build_features_batch`), `online.py` (`OnlineVehicle`).
- Все пути (`build_features`, `build_features_batch`, `OnlineVehicle.features_at`) считают признаки одной функцией `features_from_arrays` на numpy-срезах. Телеметрия — окно `(T − 30 мин, T]` (= буфер онлайн), в батче `np.searchsorted`, без `iterrows`.
- Детектор хранит момент **обнаружения** прибытия `t_det`; для `T` берутся только прибытия с `t_det ≤ T` (у проезда `t_arr < t_det` — иначе офлайн «знал» бы проезд раньше, чем онлайн).
- `OnlineVehicle`: `push` (опоздавшие пакеты встают на место, детектор перепроигрывается со снимка состояния), `target_at`, `features_at`, `derived` (`cur_dev_s`, `seg_speed_kmh`, `dwell_s`), `is_opening_or_closing_trip` (эвристика, помечена), `stop_name`, `last_fix`; `features_to_json` (NaN → None).
- **Отступление от спецификации детектора (записываю):** кандидаты `i…i+15` вместо `i…i+5` и дополнительное окно по текущему отклонению `[min(dev,0) − 4 мин, max(dev,0) + 15 мин]` (если последнее прибытие ≤ 30 мин назад) + «истечение» остановок после `plan + 25 мин`. Причина — на фактах train `i…i+5` давало покрытие 0.682, `i…i+8` — 0.669 (ниже порога 0.78): одна непойманная остановка держала указатель до 25 мин, а расширение кандидатов вызывало ложные прыжки у конечных/петель (борт проходит в 25 м от остановки, которую обслужит через 17 мин). Параметры подобраны на фактах train-дня (калибровка детектора, не признаки модели и не validate).
## Файлы
- `features/__init__.py`, `features/geo.py`, `features/io.py`, `features/stop_detector.py`, `features/build.py`, `features/online.py`
- `tests/ml/conftest.py`, `tests/ml/test_features.py`, `tests/ml/test_stop_detector.py`, `tests/ml/test_online_parity.py`
- `contracts/README.md` (раздел `features/`: пример `OnlineVehicle`, `det.cur_dev_s(T)`)
## Тесты
`pytest tests/ml/test_features.py tests/ml/test_stop_detector.py tests/ml/test_online_parity.py` → passed 18, failed 0, skipped 0 (из них slow: 5)
`pytest -m "not slow"` → passed 34, failed 0
## Метрики
| метрика | значение | порог приёмки |
|---|---|---|
| анти-утечка: full == cut == cut+мусор (50 точек test) | 0 расхождений | равенство |
| batch == single (50 точек test) | 0 расхождений | 1e-9 |
| online == offline, 2 борта test (24 + 25 точек) | 0 расхождений, target_at совпал 49/49 | 1e-6 |
| пакеты не по порядку (перемешивание ≤ 60 с) | 0 расхождений, 0 потерянных | равенство |
| детектор на фактах train: покрытие | **0.842** | ≥ 0.78 (EDA: 0.81) |
| детектор: доля \|t_arr − факт\| < 30 с | **0.774** | ≥ 0.70 (EDA: 0.72) |
| детектор: медиана ошибки / MAE | **−4.0 с** / 36.3 с | [−20, 10] (EDA: −5) |
| `build_features_batch` на train (4 434 точки) | **12.1 с** | < 90 с |
| `features_at` по 30-мин буферу, p50 | **1.98 мс** | < 5 мс |
## Пример для Расцова (backend)
```python
from features import OnlineVehicle, load_schedule, features_to_json
sched = load_schedule("data/test/schedule.csv")
veh = {tr: OnlineVehicle(rows, tr_id=tr) for tr, rows in sched.groupby("tr_id")}
# на каждый NDTP-пакет (можно не по порядку, невалидные тоже):
veh[tr].push(t, lat, lon, speed, heading, valid)
# тик каждые 5 с:
rows = []
for tr, v in veh.items():
    feats = v.features_at(now)              # None -> остановки в окне (now+10, now+15] нет, прогноз не строим
    if feats is not None:
        rows.append({"tr_id": tr, "features": features_to_json(feats)})
# POST ml-core /v1/predict {"model": "online", "rows": rows}
st = v.derived(now)                          # cur_dev_s, seg_speed_kmh, dwell_s -> VehicleState
stop_id, time_plan = v.target_at(now); name = v.stop_name(stop_id)
```
## Риски: что сработало и как закрыто
- Монотонный указатель «застревал» (покрытие 0.68) → 16 кандидатов + окно по отклонению + истечение окна; покрытие 0.84 при точности 77 % в ±30 с.
- Проезд обнаруживается позже, чем произошёл → хранится `t_det`, для `T` берутся прибытия с `t_det ≤ T`; тест анти-утечки и parity это ловят.
- Буфер онлайн 30 мин, а офлайн видел бы весь трек → все признаки телеметрии считаются по окну `(T − 30 мин, T]`.
- Пакеты не по порядку → вставка по месту + перепроигрывание детектора со снимка; отбрасываются только фиксы старше вытесненных из буфера (счётчик `n_dropped_late`).
- Часовой пояс → тест: epoch в `sample_id` == `T` как UTC.
- Ничьи по плановому времени (у организаторов 4 из 353 целевых остановок test выбраны не первой по `stop_id`) → `target_at` берёт первую по `(time_plan, stop_id)`; на 2 бортах parity-теста расхождений нет.
## Открытые вопросы / что нужно от пользователя или команды
- ИЗМЕНЕНИЕ КОНТРАКТА: в `contracts/README.md` (раздел `features/`) `det.cur_dev_s` теперь метод `det.cur_dev_s(T)`; добавлены `OnlineVehicle`, необязательный параметр `arrivals` у `build_features`, `features_to_json`. `schemas.py` не менялся. Передать Расцову.
- Backend: время пакетов передавать наивным временем датасета (как в `traffic.csv`), не UTC-смещённым.
