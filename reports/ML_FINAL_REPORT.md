# Итоговый отчёт ML (Лаврентий) — 26.09, 18:10

## 1. Задачи

| ID | Статус | Коммит | Ключевая цифра |
|---|---|---|---|
| ML-T0 окружение | ✅ | `d353b4f` | `.venv312`, catboost 1.2.10, torch 2.14 cpu |
| ML-T1 утечка, валидатор, сабмит №1 | ✅ | `1cbc225` | official test 66.98 с без early stopping |
| ML-T2 `features/` + детектор + `OnlineVehicle` | ✅ | `7c6e169` | online == offline (1e-6); детектор: покрытие 0.842, ±30 с — 77 % |
| ML-T3 модели, LOBO, причины, сабмит №2 | ✅ | `6d26617` | m_ds: official **63.0**, LOBO **75.2**, FWD 79.3 с |
| ML-T4 сервис `ml-core` + Docker | ✅ | `ce128c9` | образ 1083 МБ, холодный старт 14 с |
| ML-T5 PyTorch MLP + ONNX + бленд | ✅ | `189b8fe` | ансамбль потока LOBO **79.5 с** (MLP 83.05 ≈ CatBoost 83.02) |
| ML-T6 онлайн-replay | ✅ | `9956d29` | **100 %** прогнозов с lead ∈ [600, 900] с; вне выборки 84.0 против 177.1 с |
| ML-T8 pdoc, анти-утечка, model card | ✅ | `421080d` | `docs/api/ml/`, `docs/ANTI_LEAKAGE.md`, `docs/model_card.md` |
| ML-P1 слайды «Данные и точность» | ✅ | `177f10b` | генерируются из `model_card.json` |
| ML-P2 бизнес-эффект | ✅ | `552dc8e` | −0.79 мин ожидания; ≈ 3 900 пасс.-ч/сут ≈ 0.7 млрд ₽/год (с допущениями) |
| ML-P3 шпаргалка жюри | ✅ | `d84bdd6` | 15 ответов с числами из карточки |
| ML-P4 чек-лист сдачи | ✅ | `6eeff33` (+ ML-FINAL) | все пути существуют |
| ML-T7a слияние №1 + e2e | ✅ | `56813e5`, `7065504`, `83836e1` | pytest 130 passed; **E2E SMOKE OK**, 4 сервиса healthy |
| ML-T7b слияние №2, запуск с нуля | ⏳ 27.09 14:00 | — | зависит от следующих коммитов Расцова и Пуртова |
| ML-T7c финальное слияние, тег `v1.0` | ⏳ 27.09 18:00 | — | после код-фриза |

## 2. Метрики

| Метрика | Значение |
|---|---|
| Бейзлайн «задержка = cur_dev»: official / LOBO | 93.4 / 88.4 с |
| **m_ds (сабмит): official test / LOBO / FWD** | **63.0 / 75.2 / 79.3 с** (скор по official ≈ 0.94; 0.70 = MAE 74.2 с) |
| Ансамбль потока (CatBoost-sched 0.5 + PyTorch MLP 0.5): LOBO | 79.5 с |
| Онлайн-MAE: replay дня test (в выборке) / вне выборки (LOBO) | 61.7 / **84.0 с** против бейзлайна 163.0 / 177.1 с |
| Доля прогнозов с lead ∈ [600, 900] с | **100 %** (1 648 при тике 5 мин, 8 236 при тике 60 с) |
| q10–q90 на незнакомом борту (после калибровки ×1.8) | 80 % |
| Латентность `ml-core` `/v1/predict`, 30 строк (ансамбль + причины + интервал) | 37.5 мс на загруженном ноутбуке (без ансамбля — 9.7 мс); у Расцова в compose p50 7.6 мс |
| `features_at` по 30-минутному буферу, p50 | 2 мс |

## 3. Сабмиты — порядок загрузки

1. `submissions/sub_20260926_1522_mds_v1.csv` — основной (official 63.0, LOBO 75.2).
2. `submissions/sub_20260926_1522_mds_notod_v1.csv` — без признаков времени суток (65.4 / 75.6).
3. `submissions/sub_20260926_1522_mds_3seeds_v1.csv` — 3 сида.
4. `submissions/sub_20260926_1352_baseline_v1.csv` — legacy (67.0).

Все проходят `src/validate_submission.py`. После скора ≥ 0.70 (максимум баллов критерия) попытки не тратим: подгонка под 151 точку validate — переобучение (шум ≈ 8.9 с), а ML оценивается только по скору на сайте (QA 36:20).

## 4. Что сделать вручную

1. **Загрузить** `sub_20260926_1522_mds_v1.csv` на платформу (или дать мне адрес раздела DS и подключить Claude in Chrome — загружу сам с подтверждением каждой отправки). Скор вписать в `submissions/journal.csv` (`lb_score`) и перегенерировать документы: `python -m src.product.render_accuracy`, `python -m src.product.render_model_card`, `python -m src.product.render_qa`.
2. **Открыть доступ к репозиторию** — сейчас он приватный, ссылки для жюри отдают 404.
3. Решить судьбу `ChatExport_2026-09-26/` в `main` (адреса почты участников, аудит Пуртова).
4. Капитанский чат: хостинг или локальный запуск; эмулятор отдельным контейнером или внутри; ничья; дедлайн видео.
5. Ответить Расцову по брифу: Б3 — оставить `SystemStatusEx` в backend; Б4 — fallback без ml-core лучше прогнозировать 0 (MAE 103 против 136 у правила `0.6·cur_dev + 8`).
6. Для локального `docker compose up` без переопределения портов — остановить `agro-frontend` и `agro-bot` (заняты 3000 и 8001) или запускать с `ML_CORE_PORT=18001 FRONTEND_PORT=13000`.
7. 27.09: ML-T7b (14:00) и ML-T7c (18:00, тег `v1.0`) — запустить меня снова.

## 5. Риски, которые сработали, и как закрыты

- **Официальная `cur_dev_s` не причинна** (на 96 % = факт на последней остановке с плановым временем ≤ T, даже если борт доехал позже T) → m_ds использует её законно (она есть в validate), модели потока — восстановленные признаки; база остатка выбрана по LOBO (`zero`).
- **Детектор «застревал»** (покрытие 0.68 при i…i+5) → 16 кандидатов + окно по текущему отклонению + истечение окна: 0.842 / 77 %.
- **Official и LOBO тянут итерации в разные стороны** → выбор по LOBO (400 деревьев), official 63.0 — на границе порога ≤ 63.
- **Узкий интервал на незнакомом борту** (0.58) → калибровка по OOF LOBO до 0.80.
- **Перегруженный ноутбук** (audiodg, VPN, приложения, чужие контейнеры) → `border_count=64`, кеши OOF, латентностные тесты устойчивы к шуму; обучение моделей ~45 мин.
- **Нестабильная сеть** → повторы pip/push; все коммиты запушены.
- **Слияние**: работа Пуртова в `codex/purtov-frontend`; тест Расцова зависел от скорости машины и таймлайна старой модели; healthcheck-и падали под нагрузкой → исправлено на стыке (детали — `reports/tasks/ML-T7a.md`), код `backend/` и `frontend/` не менялся.
- **Преувеличения в питче** → слайды и шпаргалка генерируются из карточки; при вычитке исправлены 3 формулировки (LOBO 75.2 выше порога 74.2; MLP на уровне CatBoost; журнал фактов — функциональность backend).

## 6. Коммиты за период работы

```
83836e1 [ML-T7a] integration smoke results
7065504 Merge origin/codex/purtov-frontend into main (ML-T7a)
56813e5 Merge origin/rastsov/backend into main (ML-T7a)
6eeff33 [ML-P4] Submission checklist for the captain
d84bdd6 [ML-P3] Jury Q&A cheat sheet for ML and data
552dc8e [ML-P2] Business effect: EWT calculator and Moscow-scale estimate with sources
177f10b [ML-P1] Accuracy slides content generated from model card
421080d [ML-T8] pdoc for features/ml_core, anti-leakage note, model card
9956d29 [ML-T6] Online replay evaluation: horizon compliance and online MAE
189b8fe [ML-T5] PyTorch MLP member, ONNX export, LOBO-weighted blend in ml-core
ce128c9 [ML-T4] ml-core FastAPI service with /v1/predict, Dockerfile, smoke script
6d26617 [ML-T3] m_ds/m_online/m_sched with LOBO selection, quantiles, occlusion causes, submission v1
7c6e169 [ML-T2] features package: shared offline/online features, monotonic stop detector, OnlineVehicle
1cbc225 [ML-T1] Remove validate-fact leak and test early stopping, add submission validator
d353b4f [ML-T0] Python 3.12 env, pytest config, ignore rules
```
