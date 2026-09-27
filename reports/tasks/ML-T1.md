# ML-T1: Убрать утечку, валидатор сабмита, сабмит №1 — ✅
**Время:** 25 мин   **Коммит:** 1cbc225   **Пуш:** да
## Сделано
- Из `src/train.py` удалён блок «Local ground truth check for validate» (факты `test/schedule.csv` по целевым остановкам validate).
- Убраны `eval_set=(X_test, y_test)` и `early_stopping_rounds=50`; параметры фиксированы: `iterations=700, learning_rate=0.03, depth=6, loss_function='MAE', random_seed=42, verbose=0, allow_writing_files=False`. Test — только для печати MAE после обучения.
- Убран `fillna(0)` (CatBoost сам обрабатывает NaN); `sample_id` читается как строка.
- `src/validate_submission.py` — CLI-валидатор (exit 0/1): UTF-8 без BOM, `;`, заголовок, 151 строка, множество `sample_id` = `points.csv`, без дублей, `prediction` конечный в [−1000, 1500].
- `src/submission_journal.py` — сохранение `submissions/sub_<ts>_<tag>.csv` + журнал `submissions/journal.csv`.
- Переобучена текущая модель (28 legacy-признаков) → `submissions/sub_20260926_1352_baseline_v1.csv`, валидатор: OK.
## Файлы
- `src/train.py`, `src/validate_submission.py`, `src/submission_journal.py`, `models/catboost_delta_predictor.cbm` (переобучена; удаляется в ML-T3)
- `submissions/sub_20260926_1352_baseline_v1.csv`, `submissions/journal.csv`
- `tests/ml/test_validate_submission.py`, `tests/ml/test_no_leakage_static.py`
## Тесты
`pytest tests/ml/test_validate_submission.py tests/ml/test_no_leakage_static.py` → passed 18, failed 0, skipped 0
`pytest -m "not slow"` → passed 21, failed 0
## Метрики
| метрика | значение | порог приёмки |
|---|---|---|
| official test MAE, CatBoost без early stopping | **66.98 с** | ≤ 70 с |
| official test MAE, бейзлайн `cur_dev` | 93.36 с | — |
| валидатор на сабмите | OK | OK |
## Риски: что сработало и как закрыто
- Без early stopping MAE 66.98 (было 66.5 с подглядыванием в test) — порог 70 выдержан, `iterations=500` не понадобился.
- `sample_id` читается как строка во всех местах; сабмит пишется без BOM и с `\n`.
## Открытые вопросы / что нужно от пользователя или команды
- Загрузить на платформу вручную: `submissions/sub_20260926_1352_baseline_v1.csv`; скор вписать в `submissions/journal.csv` (колонка `lb_score`).
- Строка журнала: `2026-09-26T13:52:25,submissions/sub_20260926_1352_baseline_v1.csv,d353b4f,catboost_delta_legacy28,legacy28,66.98,,`
