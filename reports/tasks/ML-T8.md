# ML-T8: pdoc, анти-утечка, model card — ✅
**Время:** 25 мин   **Коммит:** 421080d   **Пуш:** да
## Сделано
- Docstrings (Google-стиль) у всех публичных функций и классов `features/` и `ml_core/` (проверено AST-сканом: пропусков нет).
- pdoc: `.venv312/Scripts/python.exe -m pdoc -o docs/api/ml features ml_core` → `docs/api/ml/` (1.4 МБ HTML, коммитим). Для формы сдачи: `docs/api/ml/index.html` (в репозитории: https://github.com/Lavrentiy123/proact-transport/tree/main/docs/api/ml).
- `docs/ANTI_LEAKAGE.md`: правила 4.2, находки (validate = test, копии бортов, один день, early stopping по test, **непричинность официальной `cur_dev_s`**), список тестов.
- `docs/model_card.md` — генерируется `src/product/render_model_card.py` из `models/model_card.json` (данные, модели, 34 признака, метрики official / LOBO / FWD / онлайн, латентность, ограничения); поле LB — из журнала сабмитов.
## Файлы
- `docs/api/ml/**`, `docs/ANTI_LEAKAGE.md`, `docs/model_card.md`, `src/product/{__init__,render_model_card,render_accuracy}.py`, `ml_core/app/predictor.py` (docstrings), `tests/ml/test_docs.py`
## Тесты
`pytest tests/ml/test_docs.py` → passed 3, failed 0
`pytest -m "not slow"` (без тестов P1/P3/P4) → passed 76; один прогон дал 1 падение латентностного теста под пиком нагрузки, повтор — зелёный (22/22 латентностных)
## Метрики
| метрика | значение | порог приёмки |
|---|---|---|
| pdoc собирается без ошибок | да | да |
| `features.html`, `ml_core.html` в `docs/api/ml/` | есть | есть |
| `TODO` в `model_card.md` | 0 (LB — поле «вписать после загрузки») | 0, кроме LB |
## Риски: что сработало и как закрыто
- pdoc мог упасть на импорте моделей → модели грузятся в lifespan, импорт `ml_core.app.main` без моделей безопасен.
- Цифры в документах разъедутся с моделями → model card генерируется из JSON, тест `tests/product/test_pitch_numbers.py` (ML-P1) сверяет слайды.
- Латентностные тесты чувствительны к перегрузке ноутбука — при повторном падении смотреть на загрузку CPU, а не на код.
## Открытые вопросы / что нужно от пользователя или команды
- После загрузки сабмита вписать скор в `submissions/journal.csv` и перегенерировать: `python -m src.product.render_model_card` и `python -m src.product.render_accuracy`.
