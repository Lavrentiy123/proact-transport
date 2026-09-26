> **Внутренний рабочий документ команды** (план, промпт или бриф хакатона), а не описание решения: часть идей здесь не реализована или изменилась. Что сделано на самом деле — [README](../../README.md), [инструкция для жюри](../../docs/JURY_GUIDE.md), [карточка модели](../../docs/model_card.md).

# Промт: задачи Лаврентия (ML, интеграция, продукт)

> **Как запускать.** Новая сессия Claude Code в корне репозитория. Модель по умолчанию Sonnet. Для ML-T2 и ML-T3 переключиться на Opus: там основная сложность и риск утечек. Первое сообщение:
> «Выполни docs/prompts/PROMPT_ML_LAVRENTIY.md по порядку задач. После каждой задачи — тесты, коммит, отчёт.»

---

## 0. Роль и цель

Ты — ML-инженер и интегратор команды «ПроАкт.Транспорт» на Хакатоне Московского транспорта 2026. Трек: прогноз задержки ТС за 10–15 минут. Ты выполняешь **все задачи Лаврентия** из [`docs/TEAM_PLAN.md`](../TEAM_PLAN.md) (разделы 3 и 4): ML-ядро, пакет признаков, сервис `ml-core`, PyTorch-модель, интеграцию веток и продуктовые материалы П1–П4.

Итог работы: все задачи ниже выполнены, покрыты тестами, закоммичены (одна задача — один коммит) и отправлены в `origin/main`. Пользователь получает короткий итоговый отчёт.

Дедлайн хакатона — 27.09 23:59 МСК, код-фриз — 27.09 18:00. Контрольные точки по времени — в разделе 5.

---

## 1. Что прочитать перед стартом (и только это)

1. `docs/TEAM_PLAN.md` — план и роли.
2. `contracts/README.md` и `contracts/schemas.py` — контракты между модулями. Их соблюдаешь строго.
3. Код: `src/train.py`, `src/feature_engineering.py`, `src/eda/build_causal_features.py`, `src/eda/validation_experiments.py`, `src/eda/stop_arrival_reconstruction.py`.
4. **Не читай целиком** `docs/DEEP_ANALYSIS_RESULT.md` (100 КБ). Нужные факты уже есть в этом промте. Если без него никак, читай только нужные строки: признаки — 80–153, эксперименты — 155–177, причины (XAI) — 209–225, детектор прибытий — 333–337, тик и алерты — 339–345.
5. **Никогда не выводи CSV целиком** (`train/traffic.csv` весит 49 МБ). Смотреть данные — только через Python: `nrows`, агрегаты, не больше 20 строк вывода.

---

## 2. Факты о данных (проверены, опирайся на них)

| Что | Значение |
|---|---|
| Период | один день 2026-01-06 (праздник), T от 02:05 до 23:55, шаг T — 5 минут |
| Точки прогноза | `labels_train.csv` 4 434 (реальных 1 141, синтетических 3 293), `labels_test.csv` 353, `validate/points.csv` 151 (11 бортов) |
| Борта | 13 реальных `tr_id` (есть в train и test), 26 синтетических `tr_id ≥ 9000000` (только train), 17 «контекстных» бортов в traffic без расписания |
| Синтетика | `9000000+2i` и `9000001+2i` — копии i-го реального борта в порядке `sorted(set(labels_test.tr_id))` со сдвигом ±1…24 мин |
| Колонки traffic | `tr_id, unit_id, event_time, location_valid, lon, lat, alt, speed (км/ч), heading, is_hist_data, …`; валидных координат 84 %, `is_hist_data` 3 % (приходят не по порядку), шаг: медиана 9.3 с |
| Колонки schedule | `tt_action_item_id` (= `target_stop_id`), `tr_id`, `time_begin` (план), `time_fact_begin` (факт, **нет в validate**), `geom` = `"POINT (lon lat)"`, `building_address` |
| Колонки точек | `sample_id` (строка `"<tr_id>_<epoch>"`), `tr_id`, `T`, `target_stop_id`, `target_time_begin`, `cur_dev_s`; в labels ещё `target_delay_s`, `target_class` |
| Время | все даты «наивные». Epoch в `sample_id` равен наивному `T`, прочитанному как UTC: `1767670500` ↔ `2026-01-06 03:35:00`. **Не применяй часовой пояс Москвы**, иначе будет сдвиг на 3 часа |
| Target | `target_delay_s`: медиана ~25 с, σ ≈ 133 с, диапазон −372…+672 с; горизонт `target_time_begin − T` — 10.05–15.0 мин |
| Сабмит | `sample_id;prediction`, разделитель `;`, заголовок обязателен, ровно 151 строка |
| Шкала скора | `score = (108.1 − MAE) / (108.1 − 60)`. Скор 0.70 (6 баллов, максимум критерия) ↔ MAE 74.2 с. Шум: SE(MAE) на 151 точке ≈ 8.9 с |
| Прошлые замеры (CatBoost по Δ, 34 признака) | официальный split train→test: бейзлайн `cur_dev` 93.4, шринк 85.9, **CatBoost 61.0**; LOBO (13 фолдов): бейзлайн 88.4, **CatBoost 76.1–76.8**; FWD (train T<14:00 → test T≥14:15): **77.4**; текущий `src/train.py` на официальном split — 66.5 |
| Утечка | validate = тот же период, что test: факты для 100 % целевых остановок validate лежат в `train/schedule.csv` и `test/schedule.csv`. **Использовать запрещено** — ни для сабмита, ни для выбора модели |

---

## 3. Окружение

- Windows 11, оболочка Git Bash. Путь репозитория содержит кириллицу (`…/Хакатоны/03_Московский_Транспорт`). **Все пути к файлам — относительные от корня репозитория**: CatBoost, ONNX и torch на Windows могут падать на абсолютных кириллических путях. Если сохранение модели всё-таки падает, сохраняй во временную ASCII-папку и переноси через `shutil.move`.
- Старое `.venv` (Python 3.9) не трогаем. Работаем в новом `.venv312` на Python 3.12: `C:/Users/Lavrentiy/AppData/Local/Programs/Python/Python312/python.exe` (3.12.10).
- Python в командах: `.venv312/Scripts/python.exe`. Тесты: `.venv312/Scripts/python.exe -m pytest …`.
- Docker Desktop 29.8 установлен. Перед Docker-задачами проверь `docker info`. Если демон не запущен, попроси пользователя запустить Docker Desktop, а пока делай следующую независимую задачу.
- Git LFS установлен (образ эмулятора `data/ndtp-telemetry-emulator.tar`, тебе он не нужен).
- Интернет медленный и нестабильный (VPN). Пуш повторяй до 3 раз с паузой 5 с. Скачивание torch (~200 МБ) запускай в фоне и не жди его.

---

## 4. Общие правила (действуют для каждой задачи)

### 4.1. Владение папками
- **Твои:** `src/` (включая `src/ml/`, `src/eval/`, `src/product/`), `features/`, `ml_core/`, `models/`, `contracts/`, `tests/ml/`, `tests/ml_core/`, `tests/product/`, `scripts/smoke_*`, `reports/`, `submissions/`, `docs/pitch/`, `docs/ANTI_LEAKAGE.md`, `docs/model_card.md`, `docs/business_effect.md`, `docs/SUBMISSION_CHECKLIST.md`, `docs/api/ml/`, `requirements/`, `pytest.ini`, `conftest.py`.
- **Чужие, не трогать:** `backend/`, `docker-compose.yml` (Расцов), `frontend/` (Пуртов). Исключение — слияния в ML-T7.
- Нужно изменить контракт — меняешь `contracts/` и пишешь в отчёте строку **«ИЗМЕНЕНИЕ КОНТРАКТА: …»**, чтобы пользователь предупредил команду. Добавлять необязательные поля можно, переименовывать и удалять — нельзя.

### 4.2. Анти-утечка (нарушение любого пункта — задача провалена)
1. Признаки для точки `(tr_id, T)` строятся только из телеметрии с `event_time ≤ T` и из **планового** расписания.
2. `time_fact_begin` запрещён в любом виде в `features/`, `ml_core/`, `src/ml/` и в инференсе. Разрешён только для target и оценки детектора в тестах.
3. `tr_id` и `unit_id` не используются как признаки. Телеметрия синтетических копий не используется как признак другого борта.
4. Никакого early stopping и подбора гиперпараметров по test или validate. Выбор — только по LOBO.
5. Метки других точек (labels) — не признаки. Никакого target encoding по всему дню.
6. Пропуски — это `NaN`, CatBoost работает с ними сам. `fillna(0)` запрещён: онлайн и офлайн должны видеть одно и то же.

### 4.3. Тесты
- Файл `pytest.ini` в корне:
  ```ini
  [pytest]
  testpaths = tests
  addopts = -q
  markers =
      slow: тесты на полных данных дольше 30 с
  ```
- После **каждой** задачи запусти:
  1. тесты этой задачи, включая `slow`: `.venv312/Scripts/python.exe -m pytest tests/<файлы задачи>`;
  2. быстрый регресс всего: `.venv312/Scripts/python.exe -m pytest -m "not slow"`.
- Коммит делается только при зелёных тестах. Если тест не проходит после двух серьёзных попыток исправить, коммить с пометкой `[WIP]` в заголовке, а в отчёте ставь статус ⚠️ с причиной. Больше на эту задачу время не трать, переходи к следующей.

### 4.4. Коммиты и пуш
- Одна задача — один коммит в `main`. Заголовок: `[ML-T<N>] <что сделано>`. В теле — ключевые метрики и результат тестов.
- После коммита: `git push origin main`, до 3 попыток. Если пуш не прошёл, продолжай работу и напиши об этом в отчёте.
- Не коммить: `.venv312/`, `cache/`, `catboost_info/`, `*.parquet`, большие промежуточные файлы. Добавь их в `.gitignore` в ML-T0.
- Файлы моделей (`models/*.cbm`, `models/*.onnx`, `models/*.json`) коммитить: они маленькие (≤ 5 МБ каждый).

### 4.5. Отчёт после каждой задачи
Сохрани в `reports/tasks/ML-T<N>.md` и коротко (до 10 строк) напиши в чат:

```markdown
# ML-T<N>: <название> — ✅ / ⚠️ / ❌
**Время:** <мин>   **Коммит:** <hash>   **Пуш:** да/нет
## Сделано
- …
## Файлы
- …
## Тесты
`<команда>` → passed N, failed N, skipped N (+ ключевые цифры)
## Метрики
| метрика | значение | порог приёмки |
## Риски: что сработало и как закрыто
- …
## Открытые вопросы / что нужно от пользователя или команды
- …
```

### 4.6. Экономия токенов
- Скрипты печатают итоговые цифры, а не поитерационные логи (CatBoost: `verbose=0`).
- Тяжёлые признаки кешируй в `cache/` (ключ — хеш версии признаков), не пересчитывай без нужды.
- Не читай файлы, которые не нужны для текущей задачи.

---

## 5. Порядок задач и контрольное время

| Задача | Суть | Должна быть готова |
|---|---|---|
| ML-T0 | окружение `.venv312`, pytest, `.gitignore` | 26.09 13:30 |
| ML-T1 | убрать утечку, валидатор, сабмит №1 | 26.09 14:30 |
| ML-T2 | пакет `features/` + детектор + `OnlineVehicle` | **26.09 18:00 (нужен Расцову)** |
| ML-T3 | модели M_ds / M_online / M_sched, LOBO, причины, сабмит №2 | 26.09 20:00 |
| ML-T4 | сервис `ml-core` + Docker | **26.09 22:00 (сквозной поток)** |
| ML-T7a | слияние №1 и сквозная проверка | 26.09 22:00 |
| ML-T5 | PyTorch MLP + ONNX + бленд | 27.09 11:00 |
| ML-T6 | онлайн-replay: горизонт и онлайн-MAE | 27.09 13:00 |
| ML-T7b | слияние №2, запуск с нуля | 27.09 14:00 |
| ML-T8 | pdoc, `ANTI_LEAKAGE.md`, `model_card.md` | 27.09 16:00 |
| ML-P1…P4 | продуктовые материалы | 27.09 17:30 |
| ML-T7c | финальное слияние, тег `v1.0` | 27.09 18:00 |
| Итог | `reports/ML_FINAL_REPORT.md` + сообщение пользователю | 27.09 18:30 |

Задачи ML-T7a/b/c зависят от веток Расцова и Пуртова. Если к контрольному времени в ветке нет новых коммитов, слей то, что есть, запиши это в отчёт и иди дальше.

---

## 6. Задачи

### ML-T0. Окружение

**Сделать:**
1. `"C:/Users/Lavrentiy/AppData/Local/Programs/Python/Python312/python.exe" -m venv .venv312`
2. Установить: `pip install "pandas>=2.2,<3" "numpy>=2,<3" "catboost==1.2.10" "scikit-learn>=1.5" pyarrow "fastapi>=0.115" "uvicorn[standard]>=0.30" "pydantic>=2.7,<3" httpx websockets pytest onnx onnxruntime pdoc`.
3. Torch — **в фоне**: `pip install torch --index-url https://download.pytorch.org/whl/cpu`. Он понадобится только в ML-T5.
4. `requirements/ml.txt` — прямые зависимости с версиями, которые установились. `requirements/ml.lock.txt` — `pip freeze`.
5. `pytest.ini` (раздел 4.3). Папки `tests/ml/`, `tests/ml_core/`, `reports/tasks/`, `submissions/` с `.gitkeep`.
6. В `.gitignore` добавить: `.venv312/`, `cache/`, `*.parquet`.
7. Тест `tests/ml/test_env.py`: импортируются `pandas, numpy, catboost, sklearn, fastapi, pydantic, onnxruntime`; версия Python ≥ 3.12; `contracts.schemas.WsMessage` валидирует `contracts/examples/ws_snapshot.json`.
8. Закоммитить в том числе `docs/prompts/PROMPT_ML_LAVRENTIY.md`.

**Приёмка:** `pytest tests/ml/test_env.py` зелёный.

**Риски:**
- Нет колеса catboost 1.2.10 под py3.12/Windows → взять ближайшую версию ≥ 1.2.7 и записать в отчёт.
- Медленная сеть → torch ставится в фоне, остальное не ждёт.
- `import contracts` не находится → в корне нужен `contracts/__init__.py` (создай пустой) и `conftest.py`, добавляющий корень в `sys.path`.

**Коммит:** `[ML-T0] Python 3.12 env, pytest config, ignore rules`

---

### ML-T1. Убрать утечку, валидатор сабмита, сабмит №1

**Сделать:**
1. В `src/train.py` удалить блок «Local ground truth check for validate» (сейчас строки ~123–144: чтение `test_sched['time_fact_begin']`, merge с `df_val_feat`, печать «Validate MAE»).
2. Убрать `eval_set=(X_test, y_test)` и `early_stopping_rounds=50`. Параметры фиксированные: `iterations=700, learning_rate=0.03, depth=6, loss_function='MAE', random_seed=42, verbose=0, allow_writing_files=False`. Test используется **только для печати MAE после обучения**.
3. Создать `src/validate_submission.py` (CLI: `python src/validate_submission.py <file.csv>`, exit 0/1). Проверки:
   - файл в UTF-8, без BOM, разделитель `;`;
   - заголовок ровно `sample_id;prediction`;
   - 151 строка данных;
   - множество `sample_id` совпадает с `data/validate/points.csv`, без дублей (`sample_id` читать как **строку**);
   - `prediction` числовой, без NaN и inf, в диапазоне [−1000, 1500].
   При ошибке — понятное сообщение: какая проверка, какие строки.
4. Сабмиты сохранять в `submissions/sub_<YYYYmmdd_HHMM>_<tag>.csv`. Журнал `submissions/journal.csv`: `created_at, file, git_hash, model, features_version, test_mae, lobo_mae, lb_score` (`lb_score` пустой, его заполняет пользователь).
5. Переобучить текущую модель и сохранить сабмит `…_baseline_v1.csv`, прогнать валидатор.

**Тесты** — `tests/ml/test_validate_submission.py`:
- корректный файл (собери из `data/sample_submission.csv`) проходит;
- падают: нет строки; дубль; NaN; разделитель `,`; неверный заголовок; BOM; лишняя строка;
- статический тест `tests/ml/test_no_leakage_static.py`: во всех `.py` в `src/train.py`, `features/`, `ml_core/`, `src/ml/` нет подстрок `time_fact_begin` и `eval_set=(X_test`. Папки, которых ещё нет, пропускать. Факты разрешены только в `tests/` и `src/eval/` (оценка, не признаки).

**Приёмка:** тесты зелёные; валидатор принимает новый сабмит; MAE на test ≤ 70 с (было 66.5 с early stopping, без него допустимо немного хуже).

**Риски:**
- Без early stopping число итераций не оптимально → если MAE на test > 70, поставить `iterations=500` и записать это. Окончательный выбор итераций — по LOBO в ML-T3.
- `sample_id` прочитан как число → сломается формат. Читать `dtype={'sample_id': str}`.
- Excel добавляет BOM и `\r\n` → валидатор ловит BOM; `\r\n` допустим.
- Загрузку на платформу ты **не делаешь** — это делает пользователь вручную. В отчёте дай путь к файлу и строку для журнала.

**Коммит:** `[ML-T1] Remove validate-fact leak and test early stopping, add submission validator`

---

### ML-T2. Пакет `features/`: одинаковые признаки офлайн и онлайн

Это ключевая задача дня: пакет нужен Расцову к 18:00.

**Структура:**
```
features/
  __init__.py      # FEATURE_NAMES, FEATURES_VERSION, build_features, build_features_batch,
                   # StopDetector, OnlineVehicle, load_schedule, load_traffic
  geo.py           # haversine_m(lon1, lat1, lon2, lat2) — R = 6 371 000 м, векторно; parse_point("POINT (lon lat)")
  io.py            # load_traffic(csv) -> DataFrame[tr_id, t, lat, lon, speed, heading, valid, unit_id]
                   # load_schedule(csv) -> DataFrame[tr_id, stop_id, time_plan, lat, lon, name]
                   # time_fact_begin сюда НЕ загружается: факты читают только тесты и src/eval/
  stop_detector.py # StopDetector
  build.py         # build_features, build_features_batch
  online.py        # OnlineVehicle — класс, который backend использует как есть
```

**Нормализация телеметрии** (`load_traffic` и `OnlineVehicle.push`): сортировка по `t`, дедуп по `(tr_id, t)`, геопризнаки — только по `valid == True` с не-NaN координатами. Пакеты `is_hist_data` вставляются по времени.

**StopDetector** (на один борт, по его плановым остановкам, отсортированным по `time_plan`):
- указатель `i` только растёт; кандидаты — остановки `i … i+5`;
- кандидат учитывается, только если время фикса в окне `[time_plan − 20 мин, time_plan + 25 мин]`;
- **прибытие:** первый фикс с расстоянием до остановки `< 25 м`; или **проезд:** расстояние дошло до минимума `< 60 м`, а следующий фикс дальше минимума на `> 15 м` — тогда время прибытия равно времени фикса с минимальным расстоянием;
- при прибытии на кандидата `k` указатель становится `k+1`, пропущенные `i…k−1` помечаются `missed`;
- публичное API: `update(t, lat, lon, speed) -> list[(stop_id, t_arr)]`, `arrivals: dict[stop_id, t_arr]`, `last_arrival(T) -> (stop_id, t_arr, rdev_s) | None` (только `t_arr ≤ T`), `cur_dev_s(T)` = `rdev` последнего прибытия ≤ T (или NaN), `lb_delay_s(T)` и `n_pending(T)` (см. признаки).

**`build_features(track, schedule, target_stop_id, target_time_plan, T, cur_dev_s, arrivals) -> dict[str, float]`** — ровно `FEATURE_NAMES` (34 штуки, порядок фиксирован, `FEATURES_VERSION = "v1"`). Окна `w ∈ {1, 3, 5, 10}` мин: фиксы с `T − w < t ≤ T`. Стоянка — `speed < 2`. Нет данных → `NaN`.

| # | Признак | Определение |
|---|---|---|
| 1 | `cur_dev_s` | подсказка (официальная в M_ds, восстановленная в M_online) |
| 2 | `horizon_s` | `target_time_plan − T`, с |
| 3–5 | `tod_sin`, `tod_cos`, `hour` | `sin/cos(2π·мин_суток/1440)`, час T |
| 6 | `n_stops_between` | плановые остановки с `T < time_plan ≤ target_time_plan` |
| 7 | `since_last_plan_s` | `T − time_plan` последней остановки с планом ≤ T |
| 8 | `rdev_last` | `rdev` последнего прибытия ≤ T |
| 9 | `rdev_age_s` | `T − t_arr` последнего прибытия |
| 10–11 | `rdev_trend5`, `rdev_trend10` | `rdev_last − rdev` последнего прибытия с `t_arr ≤ T − 5 (10) мин` |
| 12 | `n_pending` | остановки после последнего прибытия с планом ≤ T, ещё не достигнутые |
| 13 | `lb_delay_s` | `T − time_plan` первой из них, иначе 0 (нижняя граница задержки) |
| 14 | `tel_age_s` | `T − t` последнего валидного фикса |
| 15 | `last_speed` | скорость последнего фикса |
| 16–19 | `v_mean_{1,3,5,10}m` | средняя скорость в окне |
| 20–23 | `stop_ratio_{1,3,5,10}m` | доля фиксов со `speed < 2` |
| 24–27 | `disp_{1,3,5,10}m` | haversine первый → последний фикс окна (≥ 2 фиксов) |
| 28 | `v_std_5m` | std скорости за 5 мин |
| 29 | `dist_to_target_m` | haversine(последний фикс, целевая остановка) |
| 30 | `route_dist_m` | расстояние до ближайшей плановой остановки из кандидатов с `time_plan ≥ T − 15 мин` и до целевой, плюс сумма haversine по цепочке плановых остановок до целевой |
| 31 | `plan_stop_nearest_dev_s` | `T − time_plan` этой ближайшей остановки |
| 32 | `proj_delay_s` | `route_dist_m / (v_eff/3.6) − horizon_s`, `v_eff = max(v_mean_10m, 5)`, при NaN — 15 км/ч |
| 33 | `stop_in_zone_s_5m` | секунды стоянки за 5 мин в радиусе 30 м от любой плановой остановки борта (посадка) |
| 34 | `stop_out_zone_s_5m` | секунды стоянки за 5 мин вне этих зон (затор) |

Секунды стоянки считаются по интервалам между соседними фиксами: `Δt`, если на начале интервала `speed < 2`; один интервал ограничен 60 с.

**`build_features_batch(points_df, traffic_df, schedule_df, cur_dev_source='official'|'reconstructed') -> DataFrame`:**
- одна строка на точку, колонки `sample_id, tr_id, T` + `FEATURE_NAMES` (+ `target_delay_s`, если есть);
- внутри: группировка по `tr_id`, numpy-массивы, `np.searchsorted` по времени; детектор прогоняется один раз на весь трек борта, затем `arrivals` фильтруются по `≤ T`. **Без `iterrows` по traffic**;
- `reconstructed`: `cur_dev_s := rdev_last`; если NaN — `plan_stop_nearest_dev_s`; если и он NaN — NaN;
- **обязательно**: внутри для каждой точки вызывается та же логика, что в `build_features` (общая функция на numpy-срезах). Два разных расчёта — источник расхождения офлайн/онлайн.

**`OnlineVehicle(schedule_rows)`** — класс для backend:
- `push(t, lat, lon, speed, heading, valid)` — буфер последних 30 минут (deque) + детектор;
- `target_at(T) -> (stop_id, time_plan) | None` — первая плановая остановка в `(T+10 мин, T+15 мин]`;
- `features_at(T) -> dict | None` — `build_features` по буферу, `cur_dev_s` из детектора;
- `derived(T) -> {"cur_dev_s", "seg_speed_kmh", "dwell_s"}` — текущее отклонение, средняя скорость с последнего прибытия, длительность текущей стоянки (для `VehicleState`, критерий 3);
- `is_opening_or_closing_trip(T)` — эвристика: целевая остановка в первые или последние 60 минут расписания борта за день. В коде пометить как эвристику;
- `stop_name(stop_id)`.

**Тесты** — `tests/ml/test_features.py`, `tests/ml/test_stop_detector.py`, `tests/ml/test_online_parity.py`:
1. **Анти-утечка:** `build_features` для T по полному треку == по треку, обрезанному на T == по треку с мусором после T (равенство с учётом NaN) — 50 случайных точек test.
2. **Batch == single:** `build_features_batch` == поштучный `build_features` на 50 точках test, допуск 1e-9.
3. **Online == offline** (главный): для 2 реальных бортов test подаём фиксы по одному в `OnlineVehicle`, на каждом T из `labels_test` сравниваем `features_at(T)` с `build_features_batch(..., 'reconstructed')`, допуск 1e-6. Пометить `slow`, если дольше 30 с.
4. **Детектор, синтетика:** трек проезжает 3 остановки → 3 прибытия по порядку; возврат к остановке 1 не даёт повторного прибытия и не двигает указатель назад; проезд мимо на 40 м засчитывается как проезд.
5. **Детектор на фактах train** (`slow`): покрытие (доля остановок с прибытием среди тех, где был трек в окне) ≥ 0.78; доля `|t_arr − time_fact| < 30 с` ≥ 0.70; медиана ошибки в [−20, 10] с. Ориентир из EDA для правила «первый фикс в 25 м»: 81 %, 72 %, −5 с. Напечатай цифры в отчёт.
6. **Производительность:** `build_features_batch` на train (4 434 точки) < 90 с; `features_at` по 30-минутному буферу — p50 < 5 мс (для тика на 30 бортов < 150 мс).
7. `list(build_features(...).keys()) == FEATURE_NAMES`, `len == 34`.

**Приёмка:** все тесты зелёные, цифры детектора в отчёте. Пакет запушен до 18:00, в отчёте — пример использования `OnlineVehicle` для Расцова (5–10 строк кода).

**Риски:**
- Путаница рейсов (та же остановка на обратном рейсе) → монотонный указатель + окно по времени. Проверяет тест 4 и тест 5 (медиана ошибки).
- Монотонный указатель «застрял» после пропуска → кандидаты `i…i+5`; при покрытии < 0.78 расширить до `i+8` и записать это.
- Невалидные фиксы с NaN-координатами ломают haversine → фильтр `valid & notna`.
- Пакеты не по порядку (3 %) → сортировка и дедуп; в online — вставка по месту, если фикс не старше 30 минут.
- Ошибка часового пояса → в тестах сверить один `sample_id`: epoch == `T` как UTC.
- Медленный Python-цикл детектора на 50 МБ → векторные расстояния до кандидатов через numpy, цикл только по фиксам борта.
- Расхождение офлайн/онлайн из-за разной фильтрации окна → общая функция на срезах, тест 3.

**Коммит:** `[ML-T2] features package: shared offline/online features, monotonic stop detector, OnlineVehicle`

---

### ML-T3. Модели, честная валидация, причины, сабмит №2

**Файлы:** `src/ml/cv.py`, `src/ml/train_models.py`, `src/ml/causes.py`, `src/ml/predict_submission.py`.

**Валидация (`cv.py`):**
- `bus_of(tr_id)`: синтетика `9000000+2i` и `9000001+2i` → i-й реальный из `sorted(set(labels_test.tr_id))`, реальные → сами себе. Проверки (assert): 13 реальных; 26 синтетических; у каждого реального 2 копии; корреляция профиля `cur_dev_s` по времени между копией и оригиналом > 0.9 (для санити достаточно 3 пар).
- **LOBO:** объединяем точки train + test labels; `GroupKFold(n_splits=13)` по `bus` на реальных точках. Обучение — все точки (реальные + копии), у которых `bus` не отложен; тест — реальные точки отложенного борта.
- **FWD:** обучение `T < 13:45`, тест — реальные точки `T ≥ 14:00`.
- **Official:** обучение на train, тест на test (только для сравнения с LB).

**Модели** (target `Δ = y − cur_dev_s`, прогноз `ŷ = clip(cur_dev_s + Δ̂, −400, 700)`):

| Модель | Признаки | Для чего |
|---|---|---|
| `m_ds` | 34, официальная `cur_dev_s` | сабмит |
| `m_online` | 34 без `tod_sin/tod_cos/hour` + `hour_bucket = hour // 3`, `cur_dev_s` восстановленная | поток |
| `m_online_q10` / `m_online_q90` | как `m_online`, `loss_function='Quantile:alpha=0.1/0.9'`, 500 итераций | интервал q10–q90 |
| `m_sched` | `cur_dev_s, horizon_s, n_stops_between, since_last_plan_s, lb_delay_s, n_pending, hour_bucket` | fallback без телеметрии |

CatBoost: `iterations ∈ {400, 600, 800, 1200}` (выбор по среднему LOBO MAE), `learning_rate=0.04, depth=6, l2_leaf_reg=5, loss_function='MAE', verbose=0, allow_writing_files=False, thread_count=-1`. Финальные модели — среднее 5 сидов (0–4) через `catboost.sum_models(models, weights=[0.2]*5)`, обучены на train + test labels.

**Абляция TOD** в LOBO для `m_ds`: с `tod_*` и без. Если без TOD LOBO не хуже, чем на 0.5 с, для сабмита всё равно берём вариант, лучший на **official** (LB устроен как official split). Оба числа — в отчёт.

**`p_late`** — нормальное приближение по квантилям: `σ = max((q90 − q10) / 2.563, 20)`, `p_late = 1 − Φ((120 − ŷ) / σ)`. Квантили упорядочить: `q10 = min(q10, ŷ)`, `q90 = max(q90, ŷ)`.

**Причины (`causes.py`)** — групповая окклюзия, один батч `predict` на `(G+1)·N` строк:

| Группа (`cause_code`) | Признаки |
|---|---|
| `congestion` | `v_mean_*`, `stop_ratio_*`, `disp_*`, `v_std_5m`, `stop_out_zone_s_5m`, `last_speed` |
| `dwell` | `stop_in_zone_s_5m` |
| `accumulated` | `cur_dev_s`, `rdev_last`, `rdev_age_s`, `rdev_trend5`, `rdev_trend10`, `lb_delay_s`, `n_pending`, `plan_stop_nearest_dev_s`, `since_last_plan_s` |
| `hard_segment` | `route_dist_m`, `dist_to_target_m`, `proj_delay_s`, `n_stops_between`, `horizon_s` |

- «Норма» признака — медиана по обучающим строкам с `|y| < 60`. Сохраняется в `models/feature_config.json`.
- Вклад `c_g = ŷ_full − ŷ(группа заменена нормой)`. Причина — группа с максимальным `c_g` того же знака, что `ŷ`; `confidence = |c_g| / Σ|c|`.
- Правила-исключения: `tel_age_s > 60` или NaN → `low_data`; `ŷ < −60` → `early`.
- Текст причины и доказательство собирает backend. Ты отдаёшь `cause_code`, `cause_confidence`, `group_contrib_s`.

**Артефакты:**
- `models/m_ds.cbm`, `m_online.cbm`, `m_online_q10.cbm`, `m_online_q90.cbm`, `m_sched.cbm`;
- `models/feature_config.json`: списки признаков каждой модели, нормы, `FEATURES_VERSION`, `model_version = "m_online-v1-<git_hash_short>"`;
- `models/model_card.json`: все метрики.
- Старый `models/catboost_delta_predictor.cbm` удалить (его заменяет `m_ds`).

**Сабмиты:** `predict_submission.py --model m_ds` → `submissions/sub_<ts>_mds_v1.csv`. Плюс 2 честных запасных варианта (без TOD; 3 сида вместо 5). Каждый проходит валидатор и записывается в журнал.

**Тесты** — `tests/ml/test_models.py`, `tests/ml/test_causes.py`:
- маппинг `bus_of` и LOBO: ни одна точка отложенного борта или его копий не попадает в train фолда;
- модели загружаются, `predict` на 30 строк даёт конечные числа; порядок `q10 ≤ ŷ ≤ q90` у 100 % строк после упорядочивания;
- группы причин покрывают все признаки, кроме `tod_*`, `hour`, `hour_bucket`; коды из множества `{congestion, dwell, accumulated, hard_segment, early, low_data}`; `confidence ∈ [0, 1]`;
- причины для 30 строк считаются < 50 мс;
- валидатор принимает все сабмиты.

**Приёмка (цифры в отчёт таблицей):**

| Метрика | Порог |
|---|---|
| `m_ds`, official test MAE | ≤ 63 с |
| `m_ds`, LOBO MAE | ≤ 77 с |
| `m_online`, LOBO MAE | ≤ LOBO `m_ds` + 10 с |
| `m_sched`, LOBO MAE | ≤ бейзлайн `cur_dev` − 3 с |
| FWD MAE | отчёт |

**Риски:**
- Ошибка маппинга копий → утечка в LOBO и завышенная оценка. Закрывают assert и тест на пересечение фолдов.
- Переобучение на «тот же день» → всегда показывать и official, и LOBO; модель для системы выбирается по LOBO.
- Квантильные модели пересекаются → упорядочивание + тест.
- `sum_models` требует одинаковых признаков → все сиды учатся на одном и том же списке колонок.
- Скор на LB ниже 0.70 → пользователь загружает запасные варианты. Порядок отправки — в отчёте.
- Долгое обучение (13 фолдов × 4 варианта итераций × модели) → итерации подбирать только для `m_ds` и `m_online` на одном сиде, кеш признаков из `cache/`.

**Коммит:** `[ML-T3] m_ds/m_online/m_sched with LOBO selection, quantiles, occlusion causes, submission v1`

---

### ML-T4. Сервис `ml-core`

**Структура:**
```
ml_core/
  __init__.py
  app/main.py        # FastAPI
  app/predictor.py   # загрузка моделей, predict, причины, бленд (в T5)
  requirements.txt   # catboost, numpy, pandas, fastapi, uvicorn, pydantic, onnxruntime — без torch
  Dockerfile
```

**API** (модели — из `contracts/schemas.py`, их не дублировать):
- `GET /health` → `{"status": "ok"}`;
- `GET /ready` → 200, если все модели загружены, иначе 503;
- `GET /v1/model` → `model_version`, признаки, метрики из `model_card.json`;
- `POST /v1/predict`: `PredictRequest` → `PredictResponse`. `model="online"` — `m_online` + квантили + причины; `model="sched"` — `m_sched`, причина `accumulated` или `low_data`. Отсутствующий признак → NaN; лишние признаки игнорируются (их число — в логе). `latency_ms` измеряется внутри обработчика. Пустой `rows` → 200 и пустой `results`.
- Swagger на `/docs`.

**Dockerfile:** контекст сборки — корень репозитория (нужны `contracts/`, `features/`, `models/`).
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY ml_core/requirements.txt ml_core/requirements.txt
RUN pip install --no-cache-dir -r ml_core/requirements.txt
COPY contracts/ contracts/
COPY features/ features/
COPY models/ models/
COPY ml_core/ ml_core/
RUN useradd -m app
USER app
EXPOSE 8001
HEALTHCHECK --interval=10s --timeout=3s --retries=5 CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8001/ready').status==200 else 1)"
CMD ["uvicorn", "ml_core.app.main:app", "--host", "0.0.0.0", "--port", "8001"]
```
Для Расцова в отчёте — фрагмент compose: `ml-core: build: {context: ., dockerfile: ml_core/Dockerfile}, ports: ["8001:8001"]`.

**Тесты** — `tests/ml_core/test_api.py` (FastAPI `TestClient`):
- `/health` 200; `/ready` 200; `/v1/model` содержит `model_version`;
- `/v1/predict` на 30 строк, собранных через `features` из test: 30 результатов, валидация `PredictResponse`, `delay_pred_s == clip(cur_dev + delta)`, `p_late ∈ [0, 1]`, `q10 ≤ pred ≤ q90`, коды причин из множества;
- `model="sched"` работает без телематических признаков;
- `latency_ms < 100` на 30 строк; пустой батч → 200; кривое тело → 422.

**Smoke в Docker** — `scripts/smoke_ml_core.sh`: `docker build -f ml_core/Dockerfile -t proact-ml-core .` → `docker run -d --name mlc -p 8001:8001 proact-ml-core` → ждать `/ready` до 60 с → `curl` на `/v1/predict` с 2 строками → `docker rm -f mlc`. Размер образа — в отчёт (цель < 1.2 ГБ).

**Приёмка:** тесты зелёные, smoke прошёл, холодный старт до `/ready` < 30 с.

**Риски:**
- Docker Desktop не запущен → попросить пользователя, пока делать ML-T5.
- Порт 8001 занят → в отчёт, для smoke взять `-p 18001:8001`.
- Модели не попали в образ (`.dockerignore`) → проверить, что `models/*.cbm` копируются; smoke это ловит.
- Образ раздут torch → torch в runtime не ставим, PyTorch-член работает через onnxruntime.
- Импорт `contracts` в контейнере → `WORKDIR /app`, пакеты в корне `/app`.

**Коммит:** `[ML-T4] ml-core FastAPI service with /v1/predict, Dockerfile, smoke script`

---

### ML-T7a / T7b / T7c. Интеграция веток (22:00 26.09, 14:00 27.09, 18:00 27.09)

**Сделать:**
1. `git fetch origin`. Для `origin/rastsov/backend` и `origin/purtov/frontend` посмотреть новые коммиты: `git log main..origin/<ветка> --oneline`.
2. `git merge --no-ff origin/<ветка>` в `main` по очереди: сначала backend, потом frontend.
3. Конфликты решать только в общих файлах (`contracts/`, `.gitignore`, README). Код в `backend/` и `frontend/` **не переписывать** — при конфликте там остановиться и написать в отчёте, кто и что должен решить.
4. После слияния:
   - `pytest -m "not slow"`;
   - `docker compose up --build -d`;
   - проверки: `GET :8000/health`, `GET :8001/ready`, `GET :3000` отдаёт HTML, `GET :8000/api/v1/vehicles` — непустой список; из `/ws/live` получено сообщение `snapshot` с ≥ 1 бортом, у которого `forecast.lead_s ∈ [600, 900]` (скрипт `scripts/smoke_e2e.py`, использует `websockets` или `httpx-ws`, таймаут 60 с);
   - `docker compose down`.
5. Если сквозная проверка не прошла: **не пушить** сломанный `main`. Откатить локальное слияние (`git reset --hard ORIG_HEAD`, только если оно ещё не запушено) и описать в отчёте, что сломалось и у кого.
6. T7b дополнительно: запуск с нуля — `docker compose build --no-cache` и `docker compose up`, время холодного старта в отчёт.
7. T7c: после финального слияния `git tag v1.0 && git push origin main --tags`.

**Тест:** `scripts/smoke_e2e.py` (сам и есть тест) + регресс pytest.

**Приёмка:** `main` зелёный, e2e-смоук прошёл, запушено.

**Риски:**
- Ветки не обновлялись → слить что есть, записать это.
- Контракт разъехался (фронт ждёт одно поле, backend отдаёт другое) → смоук валидирует WS-сообщение через `WsMessage.model_validate`; расхождение — в отчёт с владельцем.
- Сломанный `main` у всей команды → правило п. 5.
- Долгая сборка Docker → собирать с кешем, `--no-cache` только в T7b.

**Коммит:** merge-коммиты + `[ML-T7x] integration smoke results` (если добавлены скрипты или правки).

---

### ML-T5. PyTorch MLP + ONNX + бленд (требование стека «PyTorch»)

**Файлы:** `src/ml/torch_mlp.py`, изменения в `ml_core/app/predictor.py`.

**Модель:**
- вход — признаки `m_online`; NaN → медиана train и **индикатор пропуска** для признаков с долей NaN > 5 %; стандартизация по mean/std train;
- архитектура `Linear(d→64) → ReLU → Dropout(0.1) → Linear(64→32) → ReLU → Linear(32→1)`;
- target Δ, loss L1; Adam `lr=1e-3, weight_decay=1e-4`, batch 256, **ровно 60 эпох** (без early stopping), сиды 0–4, CPU, `torch.set_num_threads(4)`.

**Оценка и бленд:** те же 13 фолдов LOBO; OOF-предсказания CatBoost и MLP; вес `w ∈ {0, 0.1, …, 0.5}` по минимальному LOBO MAE: `ŷ = (1−w)·cat + w·mlp`. Если лучший `w = 0`: взять `w = 0.1`, только если это ухудшает LOBO не больше чем на 0.5 с; иначе `w = 0` — честно записать, что MLP в системе загружен и обслуживается, но в бленд не вошёл.

**Экспорт:** `torch.onnx.export(model.eval(), …, opset_version=17, dynamic_axes={"x": {0: "batch"}})` → `models/m_online_mlp.onnx`. Препроцессинг (медианы, mean, std, список индикаторов) — в `models/feature_config.json`. В `ml-core` — onnxruntime, вес `w` из конфига.

**Тесты** — `tests/ml/test_torch_member.py`:
- ONNX == torch: `max |Δ| < 1e-4` на 100 строках;
- бленд в `ml-core` == офлайн-бленду (1e-6);
- ONNX-инференс батча 30 — p50 < 5 мс;
- `/v1/model` показывает веса членов ансамбля.

**Приёмка:** тесты зелёные; LOBO MAE бленда ≤ LOBO `m_online` + 0.5 с; веса и метрики в `model_card.json`.

**Риски:**
- torch не успел установиться → проверить фоновую установку; если сеть не даёт, отчёт ⚠️ и следующая задача.
- ONNX-экспорт с Dropout → обязательно `model.eval()`; тест равенства это ловит.
- MLP хуже CatBoost на 1.5 тыс. реальных точек → честные веса, это нормальный результат для питча.
- Сохранение `.onnx` по кириллическому пути → относительный путь или временная ASCII-папка.

**Коммит:** `[ML-T5] PyTorch MLP member, ONNX export, LOBO-weighted blend in ml-core`

---

### ML-T6. Онлайн-replay: горизонт и онлайн-MAE (доказательство для критерия 2)

**Файл:** `src/eval/online_replay_eval.py` (не в `src/ml/`: здесь читаются факты для оценки, статический тест анти-утечки на `src/eval/` не распространяется).

**Сделать:** для всех реальных бортов test прогнать фиксы по времени через `OnlineVehicle`, тик каждые 5 минут (как сетка T в датасете) и дополнительно каждые 60 с. На каждом тике: `target_at(T)` → `features_at(T)` → `ml-core` predictor (локально, без HTTP) → записать `issued_at, tr_id, stop_id, lead_s, pred, q10, q90, cause`. Факт — из `test/schedule.csv` (`time_fact_begin`; здесь это **оценка**, не признак).

**Метрики** → `reports/online_eval.md` и `models/model_card.json`:
- доля прогнозов с `lead_s ∈ [600, 900]` (ожидается 100 %);
- онлайн-MAE модели против бейзлайна «задержка = восстановленный `cur_dev`»;
- покрытие: доля тиков, где прогноз построен (нет остановки в окне или нет данных → не построен);
- распределение причин (%);
- `p50` и `p99` времени на один борт.

**Тест** — `tests/ml/test_online_eval.py` (`slow`): скрипт отрабатывает на 2 бортах; все `lead_s ∈ [600, 900]`; онлайн-MAE конечен.

**Приёмка:** отчёт с цифрами; онлайн-MAE < бейзлайна.

**Риски:**
- Онлайн-MAE сильно хуже офлайна → сравнить признаки через parity-тест ML-T2; запросить разбор по причинам.
- Путаница «факт из schedule» с признаком → факт читается только в `src/eval/`; статический тест ML-T1 должен оставаться зелёным.

**Коммит:** `[ML-T6] Online replay evaluation: horizon compliance and online MAE`

---

### ML-T8. Документация ML

**Сделать:**
1. Docstrings (Google-стиль) у всех публичных функций `features/` и `ml_core/`.
2. `.venv312/Scripts/python.exe -m pdoc -o docs/api/ml features ml_core` (HTML коммитим, в отчёте — путь для формы сдачи).
3. `docs/ANTI_LEAKAGE.md`: правила из раздела 4.2; что нашли (validate = test, копии бортов) и почему не использовали; какие тесты это проверяют (список файлов).
4. `docs/model_card.md`: данные, модели, признаки (таблица 34), метрики (LB — поле для пользователя, official, LOBO, FWD, онлайн-MAE), латентность, ограничения (один праздничный день, 13 бортов, нет `route_id`).

**Тест:** pdoc собирается без ошибок; `tests/ml/test_docs.py` — в `docs/api/ml/` есть `features.html` и `ml_core.html`; в `model_card.md` нет незаполненных `TODO`, кроме поля LB.

**Риски:** pdoc падает на импорте (ищет модели) → ленивая загрузка моделей в `predictor.py` (при старте приложения, а не при импорте).

**Коммит:** `[ML-T8] pdoc for features/ml_core, anti-leakage note, model card`

---

### ML-P1. Слайды «Данные и точность» → `docs/pitch/01_accuracy.md`

Три слайда. На каждом: заголовок; 3–5 пунктов; данные для графика (CSV в `docs/pitch/data/`); заметки докладчика на 30 с.
1. **«Что мы узнали о данных»:** один праздничный день, 13 реальных бортов и их копии; нашли утечку validate = test и **не использовали** её; честная валидация по бортам.
2. **«Точность»:** таблица — бейзлайн, скор на LB (поле для пользователя), official test, LOBO, FWD, онлайн-MAE; шкала «0.70 = MAE 74.2 с».
3. **«Горизонт и причины»:** 100 % прогнозов за 10–15 минут (из ML-T6), распределение причин, пример карточки.

**Тест:** `tests/product/test_pitch_numbers.py` — числа в `01_accuracy.md` совпадают с `models/model_card.json` (скрипт вставки чисел, а не ручной ввод).

**Риск:** цифры разъедутся с моделями после переобучения → генерировать из `model_card.json` скриптом `src/product/render_accuracy.py`.

**Коммит:** `[ML-P1] Accuracy slides content generated from model card`

---

### ML-P2. Бизнес-эффект → `docs/business_effect.md` + `src/product/ewt.py`

- Формулы: `AWT = Σh² / (2·Σh)`, `SWT = H_plan / 2`, `EWT = AWT − SWT`; пассажиро-часы = `EWT × пассажиропоток`; рубли = пассажиро-часы × стоимость часа.
- Пример на демо-данных train-дня (реальный борт и две копии как «парк маршрута»): EWT до и после рекомендации (межрейсовая стоянка 60 с), расчёт через `ewt.py`.
- Масштаб Москвы: **6 000+ ТС и 700+ маршрутов** (слова Н. Кудашова, `docs/VIDEO_TRANSCRIPT_Kudashov.md`).
- Потери перевозчика за опоздания на первом и последнем рейсе (QA-сессия, 34:08, `docs/VIDEO_TRANSCRIPT_QA_session.md`) — качественно, если нет источника с цифрами.
- **Каждое число** — либо из наших данных, либо с источником (URL). Если есть веб-поиск — используй. Иначе помечай **«допущение»** и выноси такие числа в отдельную таблицу допущений.

**Тест** — `tests/product/test_ewt.py`: равные интервалы → EWT = 0; `h = [2, 14]` мин при `H_plan = 8` → `AWT = (4 + 196) / 32 = 6.25`, `EWT = 6.25 − 4 = 2.25` мин; пустой список → ошибка.

**Риск:** неподтверждённые цифры в питче → таблица допущений, жюри увидит честность.

**Коммит:** `[ML-P2] Business effect: EWT calculator and Moscow-scale estimate with sources`

---

### ML-P3. Шпаргалка ответов жюри по ML и данным → `docs/pitch/qa_ml.md`

15 вопросов; ответ — не больше 3 предложений, с числами из `model_card.json`. Темы: утечка validate = test; один праздничный день; копии бортов; почему CatBoost; зачем PyTorch; LB против LOBO; ДТП и аварии (честно: на этих данных не обучить — это же сказал эксперт на QA); откуда `cur_dev` на потоке; как гарантируется горизонт 10–15 мин; ошибки привязки GPS (норма ±2 мин от 12.5 мин, QA 32:31); погода; масштаб до 6 000 бортов; дообучение; латентность; почему не глубокая сеть по последовательностям.

**Тест:** `tests/product/test_qa_ml.py` — 15 вопросов; нет плейсхолдеров `TODO` и `XXX`.

**Коммит:** `[ML-P3] Jury Q&A cheat sheet for ML and data`

---

### ML-P4. Чек-лист сдачи для капитана → `docs/SUBMISSION_CHECKLIST.md`

- Пять артефактов формы: что вставлять в каждое поле (путь к лучшему сабмиту из журнала; ссылка на репозиторий; якорь раздела README для жюри; ссылки на pdoc и Swagger `http://localhost:8000/docs`; текст производительности и доп. возможностей — от Расцова, П6/П8, поставь ссылку на его файл).
- Порядок отправки запасных сабмитов, если скор < 0.70.
- Открытые вопросы в капитанский чат: хостинг или локальный запуск; эмулятор отдельным контейнером или внутри решения; как решается ничья; обязательно ли видео до 23:59 27.09.
- Финальный таймлайн 27.09: 18:00 код-фриз, 21:00 репетиция, 23:00 всё загружено.

**Тест:** `tests/product/test_checklist.py` — все пути из чек-листа существуют в репозитории (кроме внешних ссылок).

**Коммит:** `[ML-P4] Submission checklist for the captain`

---

## 7. Итоговый отчёт

1. Файл `reports/ML_FINAL_REPORT.md`:
   - таблица задач: ID, статус ✅/⚠️/❌, коммит, ключевая цифра;
   - метрики: official test, LOBO, FWD, онлайн-MAE, доля прогнозов в горизонте, латентность `ml-core`;
   - какие сабмиты готовы к загрузке и в каком порядке;
   - что осталось сделать пользователю вручную (загрузить CSV, вписать скор LB в журнал и `model_card`, вопросы в капитанский чат);
   - риски, которые сработали, и как закрыты;
   - список коммитов (`git log --oneline` за период работы).
2. Коммит `[ML-FINAL] Final ML report` + пуш.
3. **Сообщение пользователю в чат — не больше 15 строк:** статус по задачам одной строкой каждая, 3–4 ключевые цифры, путь к лучшему сабмиту, что сделать вручную.
