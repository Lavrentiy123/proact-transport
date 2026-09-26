"""Генерирует ``docs/model_card.md`` из ``models/model_card.json`` и ``models/feature_config.json``.

Запуск: ``.venv312/Scripts/python.exe -m src.product.render_model_card``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from features import FEATURE_NAMES  # noqa: E402
from src.product.render_accuracy import best_lb, ensemble_label, fmt  # noqa: E402

FEATURE_DOC = {
    "cur_dev_s": "подсказка: текущее отклонение от плана (официальная в m_ds, восстановленная детектором в m_online)",
    "horizon_s": "`target_time_plan − T`, с",
    "tod_sin": "sin(2π·минута суток / 1440)",
    "tod_cos": "cos(2π·минута суток / 1440)",
    "hour": "час T",
    "n_stops_between": "плановые остановки с `T < plan ≤ target_plan`",
    "since_last_plan_s": "`T − plan` последней остановки с планом ≤ T",
    "rdev_last": "отклонение (факт детектора − план) на последнем прибытии, известном к T",
    "rdev_age_s": "`T − t_arr` последнего прибытия",
    "rdev_trend5": "`rdev_last − rdev` последнего прибытия не позже T − 5 мин",
    "rdev_trend10": "`rdev_last − rdev` последнего прибытия не позже T − 10 мин",
    "n_pending": "остановки после последнего прибытия с планом ≤ T, ещё не достигнутые",
    "lb_delay_s": "`T − plan` первой из них (нижняя граница задержки), иначе 0",
    "tel_age_s": "`T − t` последнего валидного фикса (окно 30 мин)",
    "last_speed": "скорость последнего фикса, км/ч",
    "v_mean_1m": "средняя скорость за 1 мин", "v_mean_3m": "средняя скорость за 3 мин",
    "v_mean_5m": "средняя скорость за 5 мин", "v_mean_10m": "средняя скорость за 10 мин",
    "stop_ratio_1m": "доля фиксов со скоростью < 2 км/ч за 1 мин", "stop_ratio_3m": "то же за 3 мин",
    "stop_ratio_5m": "то же за 5 мин", "stop_ratio_10m": "то же за 10 мин",
    "disp_1m": "смещение первый → последний фикс окна 1 мин, м", "disp_3m": "то же за 3 мин",
    "disp_5m": "то же за 5 мин", "disp_10m": "то же за 10 мин",
    "v_std_5m": "std скорости за 5 мин",
    "dist_to_target_m": "haversine(последний фикс, целевая остановка), м",
    "route_dist_m": "до ближайшей плановой остановки + цепочка плановых остановок до целевой, м",
    "plan_stop_nearest_dev_s": "`T − plan` ближайшей плановой остановки (оценка отклонения по позиции)",
    "proj_delay_s": "`route_dist_m / v_eff − horizon_s`, `v_eff = max(v_mean_10m, 5)` (15 км/ч без данных)",
    "stop_in_zone_s_5m": "секунды стоянки за 5 мин в 30 м от плановых остановок (посадка)",
    "stop_out_zone_s_5m": "секунды стоянки за 5 мин вне зон остановок (затор)",
}
assert list(FEATURE_DOC) == FEATURE_NAMES


def render(card: dict, cfg: dict) -> str:
    b, ds, on, sc = card["baselines"], card["m_ds"], card["m_online"], card["m_sched"]
    mlp = card.get("m_online_mlp", {})
    oe = card.get("online_eval", {})
    o300, o60 = oe.get("tick_300s", {}), oe.get("tick_60s", {})
    lat = card.get("latency", {})
    n = card["n_points"]
    L = [
        "# Model card: прогноз задержки ТС за 10–15 минут",
        "",
        f"> Сгенерировано `src/product/render_model_card.py` из `models/model_card.json` · model_version "
        f"`{card['model_version']}` · признаки `{card['features_version']}` · git `{card['git_hash']}`.",
        "",
        "## Задача и данные",
        "",
        "- Прогноз задержки прибытия на плановую остановку, до которой 10–15 минут (`target_delay_s`, с).",
        f"- Данные организаторов за один день 06.01.2026 (праздник): {n['train']} точек train, {n['test']} test, "
        "151 validate; 13 реальных бортов и 26 синтетических копий (сдвиг по времени), телеметрия NDTP ~9 с.",
        "- Признаки строятся только из телеметрии до момента прогноза и планового расписания (см. `docs/ANTI_LEAKAGE.md`).",
        "",
        "## Модели",
        "",
        "| Модель | Для чего | Признаки | База остатка | Деревьев × сидов |",
        "|---|---|---|---|---|",
    ]
    for name, why in [("m_ds", "сабмит (официальная подсказка cur_dev)"), ("m_online", "поток (восстановленная подсказка)"),
                      ("m_online_q10", "нижняя граница интервала"), ("m_online_q90", "верхняя граница интервала"),
                      ("m_sched", "fallback без телеметрии")]:
        m = cfg["models"][name]
        L.append(f"| `{name}` | {why} | {len(m['features'])} | `{m['base_mode']}` | {m['iterations']} × {len(m['seeds'])} |")
    L += [
        "",
        "CatBoost (MAE; lr 0.04, depth 6, l2 5), прогноз `ŷ = clip(база + Δ̂, −400, 700)`; число деревьев и база "
        "остатка выбраны по LOBO. Финальные модели обучены на train + test labels, 5 сидов усреднены (`sum_models`).",
    ]
    if mlp:
        L += [f"Поток обслуживает ансамбль: {ensemble_label(card)} (веса выбраны по LOBO). PyTorch MLP — "
              f"{mlp['arch']}, {mlp['epochs']} эпох × {mlp['seeds']} сидов, экспорт в ONNX, в сервисе — onnxruntime. "
              f"LOBO: CatBoost m_online {fmt(mlp['lobo_mae_cat'])} с, MLP {fmt(mlp['lobo_mae_mlp'])} с, "
              f"ансамбль {fmt(mlp['lobo_mae_blend'])} с."]
    L += [
        "Интервал q10–q90 — квантильные CatBoost; `p_late = 1 − Φ((120 − ŷ)/σ)`, `σ = max((q90 − q10)/2.563, 20)`.",
        "Причина — групповая окклюзия: congestion / dwell / accumulated / hard_segment + правила low_data и early.",
        "",
        f"## Признаки (34, `FEATURES_VERSION = {card['features_version']}`)",
        "",
        "| # | Признак | Определение |",
        "|---|---|---|",
    ] + [f"| {i} | `{k}` | {v} |" for i, (k, v) in enumerate(FEATURE_DOC.items(), start=1)] + [
        "",
        "Окна телеметрии `(T − w, T]`, стоянка — скорость < 2 км/ч, пропуск — NaN.",
        "",
        "## Метрики (MAE, с)",
        "",
        "| Оценка | Бейзлайн `cur_dev` | m_ds | m_online | m_sched |",
        "|---|---|---|---|---|",
        f"| Скор на сайте (LB, validate) | — | {best_lb()} | — | — |",
        f"| Official (train → test) | {fmt(b['official_cur_dev'])} | {fmt(ds['official_mae'])} | {fmt(on['official_mae'])} | — |",
        f"| LOBO, 13 бортов (основная) | {fmt(b['lobo_cur_dev_official'])} (восст.: {fmt(b['lobo_cur_dev_reconstructed'])}) "
        f"| {fmt(ds['lobo_mae'])} | {fmt(on['lobo_mae'])} | {fmt(sc['lobo_mae'])} |",
        f"| FWD (T < 13:45 → T ≥ 14:00) | {fmt(b['fwd_cur_dev'])} | {fmt(ds['fwd_mae'])} | {fmt(on['fwd_mae'])} | {fmt(sc['fwd_mae'])} |",
    ]
    if mlp:
        L.append(f"| LOBO, ансамбль потока ({ensemble_label(card)}) | — | — | {fmt(mlp['lobo_mae_blend'])} (MLP отдельно {fmt(mlp['lobo_mae_mlp'])}) | — |")
    oos = oe.get("out_of_sample_lobo", {})
    if oos:
        L += [f"| Онлайн вне выборки (LOBO, {oos['n_points']} точек test) | {fmt(oos['online_mae_baseline_s'])} (восст.) | — | "
              f"{fmt(oos['online_mae_model_s'])} | — |"]
    if o300:
        L += [f"| Онлайн-replay дня test, тик 5 мин (в выборке) | {fmt(o300['online_mae_baseline_s'])} (восст.) | — | "
              f"{fmt(o300['online_mae_model_s'])} | — |",
              f"| Онлайн-replay дня test, тик 60 с (в выборке) | {fmt(o60['online_mae_baseline_s'])} (восст.) | — | "
              f"{fmt(o60['online_mae_model_s'])} | — |"]
    L += [
        "",
        f"Абляция времени суток (m_ds): LOBO с TOD {fmt(ds['lobo_mae'])} / без {fmt(ds['lobo_mae_notod'])}; official с TOD "
        f"{fmt(ds['official_mae_tod'])} / без {fmt(ds['official_mae_notod'])}. Шкала платформы: 0.70 = MAE 74.2 с; "
        "шум на 151 точке validate ≈ 8.9 с.",
        f"Интервал q10–q90 на LOBO накрывал факт в {100 * on['interval_q10_q90_coverage_lobo']:.0f} % случаев; после "
        f"калибровки ширины ×{on.get('interval_scale', 1.0)} по OOF — в "
        f"{100 * on.get('interval_q10_q90_coverage_lobo_calibrated', on['interval_q10_q90_coverage_lobo']):.0f} % "
        f"(медианная ширина {fmt(on.get('interval_width_median_calibrated_s', on['interval_width_median_s']), 0)} с).",
        "",
        "## Горизонт и латентность",
        "",
    ]
    if o60:
        L += [f"- Доля прогнозов с lead ∈ [600, 900] с: {100 * o60['share_lead_in_window']:.1f} % ({o60['forecasts_total']} прогнозов, тик 60 с).",
              f"- Время на борт в тике (признаки + доля батча ml-core): p50 {o60['per_bus_ms_p50']:.1f} мс, p99 {o60['per_bus_ms_p99']:.1f} мс."]
    if lat:
        L += [f"- `/v1/predict` на 30 строк: {lat.get('predict_30_ms_p50', float('nan')):.1f} мс (p50)."]
    L += [
        "- `features_at` по 30-минутному буферу: ~2 мс (p50); признаки для 4 434 точек train — ~12 с.",
        "",
        "## Ограничения",
        "",
        "- Один праздничный день: нет будней, часов пик рабочего дня, сезонности и погоды — перенос на будни не проверен.",
        "- 13 реальных бортов; копии — сдвинутые по времени дубли, новой информации о маршрутах они почти не дают.",
        "- Нет `route_id`/`trip_id`: «первый/последний рейс» определяется эвристикой по времени, рейсы — по плановому расписанию.",
        "- Восстановленное детектором отклонение шумнее официальной подсказки (LOBO бейзлайна "
        f"{fmt(b['lobo_cur_dev_reconstructed'])} против {fmt(b['lobo_cur_dev_official'])} с) — поэтому онлайн-модель "
        "учится на восстановленном отклонении, а не на официальном.",
        "- ДТП, перекрытия и погоду модель не видит: на этих данных их не обучить (так же сказал эксперт на QA-сессии).",
        "",
    ]
    return "\n".join(L)


def main() -> int:
    card = json.loads((ROOT / "models" / "model_card.json").read_text(encoding="utf-8"))
    cfg = json.loads((ROOT / "models" / "feature_config.json").read_text(encoding="utf-8"))
    out = ROOT / "docs" / "model_card.md"
    out.write_text(render(card, cfg), encoding="utf-8")
    print(f"written {out.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
