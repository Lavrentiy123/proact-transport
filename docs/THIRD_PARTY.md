# Внешние данные, сервисы и библиотеки

По п. 9.4 Положения внешние данные и API допускаются, если они доступны в РФ и открыты, и их нужно указать в
документации. Ниже — полный список для работающей системы, обучения и документации.

## Данные

| Что | Где используется | Условия |
|---|---|---|
| Датасет организаторов задачи «Предиктор изменений в графике транспорта»: телеметрия NDTP, плановое расписание, точки `labels` за 06.01.2026 | обучение моделей, replay потока на стенде | предоставлен организаторами хакатона |

Других внешних данных (погода, пробки, ДТП, сторонние API) система не использует.

## Внешние сервисы во время работы

| Сервис | Для чего | Условия |
|---|---|---|
| [OpenFreeMap](https://openfreemap.org), стиль `https://tiles.openfreemap.org/styles/dark` — векторные тайлы, шрифты подписей, спрайты | подложка карты на дашборде | бесплатно, без ключа и регистрации; данные © участники OpenStreetMap (ODbL 1.0), схема OpenMapTiles; атрибуция выводится на карте (правый нижний угол) |

Если подложка недоступна, дашборд работает без неё: сеть маршрутов, борта и алерты рисуются из данных backend.
Больше система никуда наружу не обращается: прогноз считает собственный сервис `ml-core`, внешних ML- и облачных API нет.
Адрес стиля меняется переменной сборки `VITE_MAP_STYLE_URL` (новый хост нужно добавить в CSP `frontend/nginx.conf`).

## Библиотеки в работающей системе

**Python (backend, ml-core)**

| Библиотека | Версия | Лицензия |
|---|---|---|
| FastAPI | 0.141.1 | MIT |
| Starlette (зависимость FastAPI) | 1.7 | BSD-3-Clause |
| Uvicorn | 0.54.0 | BSD-3-Clause |
| Pydantic | 2.13.5 | MIT |
| HTTPX | 0.28.1 | BSD-3-Clause |
| NumPy | 2.5.3 | BSD-3-Clause |
| pandas | 2.3.3 | BSD-3-Clause |
| SciPy | 1.18.1 | BSD-3-Clause |
| six | 1.17.0 | MIT |
| CatBoost | 1.2.10 | Apache-2.0 |
| ONNX Runtime | 1.30.0 | MIT |

**Frontend (дашборд)**

| Библиотека | Версия | Лицензия |
|---|---|---|
| React, React DOM | 19.3 | MIT |
| MapLibre GL JS | 6.11 | BSD-3-Clause |
| lucide-react (иконки) | 1.48 | ISC |
| Шрифты Inter и JetBrains Mono (`@fontsource`, встроены в сборку, без внешних CDN) | 5.3 | SIL OFL 1.1 |

## Обучение, анализ, тесты и документация

| Библиотека | Лицензия |
|---|---|
| PyTorch (MLP, экспорт в ONNX) | BSD-3-Clause |
| ONNX | Apache-2.0 |
| scikit-learn, joblib | BSD-3-Clause |
| LightGBM (эксперименты) | MIT |
| Shapely (геометрия в анализе данных) | BSD-3-Clause |
| PyArrow | Apache-2.0 |
| Matplotlib | Matplotlib License (на основе PSF) |
| Plotly | MIT |
| pytest | MIT |
| pdoc (документация API) | MIT-0 |
| Vite, Vitest, @vitejs/plugin-react, Testing Library, jsdom, ws | MIT |
| TypeScript, Playwright | Apache-2.0 |

## Инфраструктура

| Компонент | Лицензия |
|---|---|
| Docker Engine, Docker Compose | Apache-2.0 |
| Базовые образы `python:3.12-slim`, `node:24-alpine` (сборка фронтенда) | лицензии Python (PSF) и Node.js (MIT) |
| nginx (`nginx:1.29-alpine`, раздача дашборда и прокси API) | BSD-2-Clause |

Точные версии Python-пакетов — в `backend/requirements.txt`, `ml_core/requirements.txt`, `ml_core/requirements-nodeps.txt`,
`requirements.txt`; фронтенда — в `frontend/package.json` и `frontend/package-lock.json`.
