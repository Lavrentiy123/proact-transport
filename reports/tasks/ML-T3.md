# ML-T3: Модели, честная валидация, причины, сабмит №2 — ✅
**Время:** 70 мин (из них 43 мин — обучение на ноутбуке)   **Коммит:** 6d26617   **Пуш:** да
## Сделано
- `src/ml/cv.py`: `bus_of` (копия → оригинал), проверки маппинга (13 реальных, 26 копий, по 2 на борт; корреляция профиля `cur_dev_s` при лучшем сдвиге ±25 мин на первых 3 парах: 0.930 / 0.916 / 0.907; совпадение координат остановок 26/26), LOBO (`GroupKFold(13)` по борту+копиям), FWD, official.
- `src/ml/dataset.py`: признаки train/test/validate через пакет `features/` с кешем в `cache/` (ключ — версия + md5 исходников).
- `src/ml/train_models.py`: m_ds, m_ds_notod, m_online (+ q10/q90), m_sched. Итерации {400, 600, 800, 1200} и **база остатка** (`cur_dev` / `zero`) — по LOBO; финальные модели — `sum_models` 5 сидов на train + test labels; нормы для причин; `models/feature_config.json`, `models/model_card.json`. После обучения — калибровка ширины q10–q90 по OOF LOBO.
- `ml_core/inference.py` (общий код офлайн/ml-core): клип, база, квантили, `p_late`, групповая окклюзия, правила `low_data`/`early`. `src/ml/causes.py` — обёртка (образ ml-core не содержит `src/`, поэтому логика живёт в `ml_core`).
- `src/ml/predict_submission.py`: 3 сабмита, все прошли валидатор и записаны в журнал.
- Удалён `models/catboost_delta_predictor.cbm` (его заменяет `m_ds`).
## Файлы
- `src/ml/{__init__,cv,dataset,train_models,causes,predict_submission}.py`, `ml_core/{__init__,inference}.py`
- `models/m_ds.cbm`, `m_ds_notod.cbm`, `m_ds_3seeds.cbm`, `m_online.cbm`, `m_online_q10.cbm`, `m_online_q90.cbm`, `m_sched.cbm`, `feature_config.json`, `model_card.json`
- `submissions/sub_20260926_1522_{mds,mds_notod,mds_3seeds}_v1.csv`, `submissions/journal.csv`
- `tests/ml/test_models.py`, `tests/ml/test_causes.py`
## Тесты
`pytest tests/ml/test_models.py tests/ml/test_causes.py` → passed 13, failed 0 (причины для 30 строк — 6.7 мс)
`pytest -m "not slow"` (без тестов следующих задач) → passed 63, failed 0
## Метрики
| Метрика | Значение | Порог |
|---|---|---|
| `m_ds`, official test MAE (5 сидов, 400 деревьев) | **63.00 с** (62.999) | ≤ 63 с |
| `m_ds`, LOBO MAE | **75.24 с** | ≤ 77 с |
| `m_ds` без TOD: LOBO / official | 75.58 / 65.41 с | отчёт → сабмит с TOD |
| `m_ds`, FWD | 79.34 с | отчёт |
| `m_online`, LOBO (база `zero`) | **83.02 с** | ≤ 75.24 + 10 = 85.24 |
| `m_online`, FWD / official | 83.09 / 69.12 с | отчёт |
| `m_sched`, LOBO (база `zero`) | **81.50 с** | ≤ бейзлайн восст. `cur_dev` 161.7 − 3 (и < «ноль» 93.0) |
| бейзлайн `cur_dev` официальный: LOBO / official / FWD | 88.38 / 93.36 / 87.11 с | — |
| q10–q90 на LOBO: до / после калибровки ×1.75 | 0.58 / **0.80** | отчёт |
## Риски: что сработало и как закрыто
- **Официальная подсказка `cur_dev_s` «знает будущее».** Проверили на train: на 96 % (MAE 0.8 с) она равна факту на последней остановке с **плановым** временем ≤ T — даже если борт доехал до неё после T. На потоке такого знания нет, поэтому восстановленное детектором отклонение как прогноз хуже нуля (161.7 против 93.0). Закрыто: для m_online база остатка выбрана по LOBO — `zero` (83.0) против `cur_dev` (89.6); это честная цена потока.
- **m_sched (7 признаков расписания) на LOBO лучше m_online (81.5 против 83.0)**: телеметрические признаки переобучаются на «чужом» борту. Среднее m_online и m_sched на OOF — 80.8; вношу m_sched членом ансамбля в ML-T5 (веса по LOBO).
- Official и LOBO тянут итерации в разные стороны (official лучше на 800 деревьях — 58.8 с на сиде 0, LOBO — на 400). Оставлен честный выбор по LOBO; official 63.0 — на границе порога, но для скора это 0.94 при максимуме баллов с 0.70.
- Долгое обучение на ноутбуке (i5-10210U, фоновые audiodg/VPN) → `border_count=64` (в 2.3 раза быстрее, official на тесте не хуже: 58.8 против 60.3 при 254), префиксы деревьев `ntree_end` вместо переобучения на каждое число итераций, кеш OOF в `cache/t3/`.
- Ошибка маппинга копий → assert по трём проверкам + тест: ни одна точка отложенного борта и его копий не в train фолда.
- Узкий интервал на незнакомом борту (0.58) → калибровка множителем по OOF LOBO (1.75 → 0.80), в конфиге `interval_scale`.
## Сабмиты: порядок загрузки
1. `submissions/sub_20260926_1522_mds_v1.csv` — основной (official 63.0, LOBO 75.2).
2. `submissions/sub_20260926_1522_mds_notod_v1.csv` — без времени суток (official 65.4, LOBO 75.6).
3. `submissions/sub_20260926_1522_mds_3seeds_v1.csv` — 3 сида.
4. `submissions/sub_20260926_1352_baseline_v1.csv` — legacy (official 67.0).
Скор 0.70 ↔ MAE 74.2 с: все варианты по official ≈ 0.86–0.94; после первого скора ≥ 0.70 попытки не тратим.
## Открытые вопросы / что нужно от пользователя или команды
- Загрузка на платформу: нужен адрес раздела Data Science и подключённый Claude in Chrome (или загрузка вручную); скор — в `submissions/journal.csv` (`lb_score`).
