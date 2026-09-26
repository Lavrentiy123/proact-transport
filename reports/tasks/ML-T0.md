# ML-T0: Окружение — ✅
**Время:** 35 мин   **Коммит:** см. `git log --grep "ML-T0"`   **Пуш:** см. ниже
## Сделано
- `.venv312` на Python 3.12.10; установлены pandas 2.3.3, numpy 2.5.3, catboost 1.2.10 (колесо под py3.12/Windows есть), scikit-learn 1.9.1, fastapi 0.141.1, pydantic 2.13.5, onnxruntime 1.30.0, pdoc 16.0.0 и др.
- torch 2.14.0+cpu поставлен в фоне (для ML-T5).
- `requirements/ml.txt` (прямые зависимости), `requirements/ml.lock.txt` (`pip freeze`).
- `pytest.ini`, корневой `conftest.py` (корень в `sys.path`), пустой `contracts/__init__.py`.
- Папки `tests/ml/`, `tests/ml_core/`, `reports/tasks/`, `submissions/` с `.gitkeep`; в `.gitignore` добавлены `.venv312/`, `cache/`, `*.parquet`.
- В коммит включён `docs/prompts/PROMPT_ML_LAVRENTIY.md`.
## Файлы
- `requirements/ml.txt`, `requirements/ml.lock.txt`, `pytest.ini`, `conftest.py`, `contracts/__init__.py`, `tests/ml/test_env.py`, `.gitignore`
## Тесты
`.venv312/Scripts/python.exe -m pytest tests/ml/test_env.py` → passed 3, failed 0, skipped 0
## Метрики
| метрика | значение | порог приёмки |
|---|---|---|
| test_env | 3/3 | зелёный |
## Риски: что сработало и как закрыто
- Нестабильная сеть (VPN): pip получал `ConnectionResetError`, первая установка молча не прошла → повтор с `--retries 10 --timeout 60`, всё установилось.
- catboost 1.2.10 под py3.12 нашёлся, замена версии не понадобилась.
## Открытые вопросы / что нужно от пользователя или команды
- Нет.
