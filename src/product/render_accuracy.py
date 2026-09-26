"""Генерирует слайды «Данные и точность» (``docs/pitch/01_accuracy.md``) и CSV для графиков из
``models/model_card.json`` — чтобы цифры в питче не разъезжались с моделями после переобучения.

Запуск: ``.venv312/Scripts/python.exe -m src.product.render_accuracy``.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CARD = ROOT / "models" / "model_card.json"
OUT = ROOT / "docs" / "pitch" / "01_accuracy.md"
DATA_DIR = ROOT / "docs" / "pitch" / "data"
SCORE_MAX_MAE, SCORE_ZERO_MAE = 60.0, 108.1  # score = (108.1 − MAE) / (108.1 − 60)
CAUSE_RU = {"congestion": "затор на перегоне", "dwell": "долгая посадка", "accumulated": "накопленное отставание",
            "hard_segment": "сложный участок", "early": "опережение", "low_data": "мало данных"}


def score_of(mae: float) -> float:
    """Скор платформы по MAE: ``(108.1 − MAE) / (108.1 − 60)``."""
    return (SCORE_ZERO_MAE - mae) / (SCORE_ZERO_MAE - SCORE_MAX_MAE)


def best_lb(journal: Path = ROOT / "submissions" / "journal.csv") -> str:
    """Лучший скор LB из журнала (заполняет пользователь) или поле для заполнения."""
    if not journal.exists():
        return "___ (вписать после загрузки)"
    vals = []
    with open(journal, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            try:
                vals.append(float(r.get("lb_score") or ""))
            except ValueError:
                pass
    return f"{max(vals):.3f}" if vals else "___ (вписать после загрузки)"


def fmt(x, nd=1) -> str:
    return "—" if x is None else f"{x:.{nd}f}"


MEMBER_RU = {"catboost": "CatBoost", "catboost_sched": "CatBoost по расписанию", "torch_mlp_onnx": "PyTorch MLP"}


def ensemble_label(card: dict) -> str:
    """Состав ансамбля с весами, например «CatBoost по расписанию 0.5 + PyTorch MLP 0.5»."""
    w = card.get("ensemble_weights", {})
    parts = [f"{MEMBER_RU.get(k, k)} {v:g}" for k, v in w.items() if v > 0]
    return " + ".join(parts) if parts else "CatBoost"


def rows_accuracy(card: dict) -> list[tuple[str, str, str]]:
    """Строки таблицы «Точность»: (метрика, MAE, скор)."""
    b, ds, on = card["baselines"], card["m_ds"], card["m_online"]
    oe = card.get("online_eval", {}).get("tick_300s", {})
    blend = card.get("m_online_mlp", {})
    rows = [
        ("Бейзлайн «задержка = cur_dev», official test", fmt(b["official_cur_dev"]), fmt(score_of(b["official_cur_dev"]), 2)),
        ("Бейзлайн «задержка = cur_dev», LOBO по бортам", fmt(b["lobo_cur_dev_official"]), fmt(score_of(b["lobo_cur_dev_official"]), 2)),
        ("**Скор на сайте (LB, validate)**", "—", best_lb()),
        ("CatBoost m_ds, official test (train → test)", fmt(ds["official_mae"]), fmt(score_of(ds["official_mae"]), 2)),
        ("CatBoost m_ds, LOBO (13 бортов, честно)", fmt(ds["lobo_mae"]), fmt(score_of(ds["lobo_mae"]), 2)),
        ("CatBoost m_ds, FWD (до 13:45 → после 14:00)", fmt(ds["fwd_mae"]), fmt(score_of(ds["fwd_mae"]), 2)),
        ("Поток: m_online, LOBO (cur_dev восстановлен детектором)", fmt(on["lobo_mae"]), fmt(score_of(on["lobo_mae"]), 2)),
    ]
    if blend:
        rows.append((f"Поток: ансамбль ({ensemble_label(card)}), LOBO", fmt(blend["lobo_mae_blend"]),
                     fmt(score_of(blend["lobo_mae_blend"]), 2)))
    oos = card.get("online_eval", {}).get("out_of_sample_lobo", {})
    if oos:
        rows.append(("Поток: онлайн-прогноз для незнакомого борта (LOBO, точки test)", fmt(oos["online_mae_model_s"]), "—"))
        rows.append(("Поток: бейзлайн «восстановленный cur_dev» на тех же точках", fmt(oos["online_mae_baseline_s"]), "—"))
    live = card.get("stream_live", {})
    if live:
        rows.append(("Живой поток в Docker (replay ×10 по NDTP, журнал backend, в выборке)", fmt(live["online_mae_model_s"]), "—"))
        rows.append(("Живой поток: бейзлайн «восстановленный cur_dev»", fmt(live["online_mae_baseline_s"]), "—"))
    elif oe:
        rows.append(("Поток: replay дня test, тик 5 мин (в выборке — проверка потока)", fmt(oe["online_mae_model_s"]), "—"))
    return rows


def render(card: dict) -> str:
    ds = card["m_ds"]
    oe = card.get("online_eval", {}).get("tick_60s", {})
    causes = oe.get("causes_pct", {})
    n = card["n_points"]
    acc = rows_accuracy(card)
    lines = [
        "# Слайды «Данные и точность»",
        "",
        "> Сгенерировано `src/product/render_accuracy.py` из `models/model_card.json` "
        f"(model_version `{card.get('model_version', '?')}`). Руками не править — перегенерировать.",
        "",
        "## Слайд 1. Что мы узнали о данных",
        "",
        "- Один день — 06.01.2026 (праздник): train, test и validate из одного дня.",
        f"- 13 реальных бортов и 26 синтетических копий (сдвиг ±1…24 мин); всего {n['pool']} точек, "
        f"реальных {n['pool_real']}.",
        "- Нашли утечку: validate — тот же период, что test, факты для 100 % целевых остановок validate лежат в "
        "`schedule.csv`. **Не использовали** — ни для сабмита, ни для выбора модели.",
        "- Честная оценка: LOBO — отложенный борт вместе с копиями; модели и число деревьев выбираем только по нему.",
        "",
        "**График:** `docs/pitch/data/data_overview.csv` — точки по бортам (реальные / копии).",
        "",
        "**Заметки докладчика (30 с):** «Данных — один праздничный день и 13 настоящих автобусов, остальное — их копии "
        "со сдвигом. Мы нашли, что проверочная выборка совпадает по времени с тестом и её ответы лежат в расписании, — и "
        "сознательно этим не пользовались. Качество меряем честно: прячем целый автобус вместе с копиями и проверяем на нём.»",
        "",
        "## Слайд 2. Точность",
        "",
        "| Оценка | MAE, с | Скор |",
        "|---|---|---|",
    ] + [f"| {a} | {b} | {c} |" for a, b, c in acc] + [
        "",
        "- Шкала платформы: скор = (108.1 − MAE) / 48.1; **0.70 = MAE 74.2 с** (максимум баллов критерия).",
        f"- m_ds: {ds['iterations']} деревьев × 5 сидов, 34 признака; вариант сабмита — "
        f"{'с признаками' if ds['submission_variant'] == 'tod' else 'без признаков'} времени суток.",
        "- Шум оценки на 151 точке validate: SE(MAE) ≈ 8.9 с — поэтому модель выбираем по LOBO, а не по LB.",
        "",
        "**График:** `docs/pitch/data/accuracy.csv` — столбцы MAE по оценкам + линия 74.2 с.",
        "",
        "**Заметки докладчика (30 с):** «Бейзлайн "
        f"{fmt(card['baselines']['official_cur_dev'])} секунды, наша модель — {fmt(ds['official_mae'])} на тесте организаторов "
        f"и {fmt(ds['lobo_mae'])} при честной проверке на незнакомом автобусе. Порог максимального балла — 74.2 секунды: "
        + ("мы проходим его и на сайте, и на незнакомом автобусе.»" if ds["lobo_mae"] <= 74.2 else
           "на сайте (тот же день и те же борта) мы проходим его с запасом, а на незнакомом автобусе держимся у самой "
           "границы — это честная цена переноса на новый борт.»"),
        "",
        "## Слайд 3. Горизонт и причины",
        "",
    ]
    if oe:
        lines += [
            f"- **{100 * oe['share_lead_in_window']:.0f} % прогнозов** выданы за 10–15 минут до прибытия "
            f"({oe['forecasts_total']} прогнозов на replay дня test, тик 60 с): прогноз строится только для остановки "
            "в окне (T+10, T+15].",
        ]
        live = card.get("stream_live", {})
        if live:
            lines.append(
                f"- **То же на живом потоке** (docker compose, NDTP, журнал backend): {100 * live['share_lead_in_window']:.0f} % "
                f"прогнозов в окне 10–15 мин, онлайн-MAE {fmt(live['online_mae_model_s'])} с против "
                f"{fmt(live['online_mae_baseline_s'])} с у бейзлайна на {int(live['resolved_total'])} сверенных прогнозах; "
                f"инференс ансамбля p50 {live['infer_ms_p50']:.0f} мс, p99 {live['infer_ms_p99']:.0f} мс.")
        oos = card.get("online_eval", {}).get("out_of_sample_lobo", {})
        if oos:
            lines.append(f"- Онлайн-прогноз для незнакомого борта: MAE {fmt(oos['online_mae_model_s'])} с против "
                         f"{fmt(oos['online_mae_baseline_s'])} с у бейзлайна «восстановленное отклонение».")
        cal = card["m_online"].get("interval_q10_q90_coverage_lobo_calibrated")
        lines += [
            (f"- Интервал q10–q90 на незнакомом борту накрывает факт в {100 * cal:.0f} % случаев (калибровка по LOBO)."
             if cal else f"- Факт попадает в интервал q10–q90 в {100 * oe['interval_coverage']:.0f} % случаев."),
            "- Причины прогнозов: " + ", ".join(f"{CAUSE_RU.get(k, k)} — {v:.0f} %" for k, v in
                                               sorted(causes.items(), key=lambda kv: -kv[1])) + ".",
        ]
    else:
        lines += ["- (данные онлайн-replay появятся после ML-T6)"]
    lines += [
        "- Формат карточки (макет из `contracts/examples/`): «Борт 131672: +6 мин к ост. «Ул. Гарибальди» через 12 мин · причина: затор на перегоне "
        "(4 км/ч за 5 мин, норма 18) · рекомендация: держать 24 км/ч».",
        "",
        "**График:** `docs/pitch/data/horizon.csv` (распределение lead) и `docs/pitch/data/causes.csv` (доли причин).",
        "",
        "**Заметки докладчика (30 с):** «Каждый прогноз выдаётся строго за 10–15 минут — это видно в журнале прогнозов. "
        "И мы не только говорим «опоздает», но и почему: затор, долгая посадка или накопленное отставание — "
        "диспетчер сразу понимает, что делать.»",
        "",
    ]
    return "\n".join(lines)


def write_data(card: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(DATA_DIR / "accuracy.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["metric", "mae_s", "score"])
        for a, b, c in rows_accuracy(card):
            w.writerow([a.replace("*", ""), b, c])
        w.writerow(["Порог максимального балла (score 0.70)", "74.2", "0.70"])
    oe = card.get("online_eval", {}).get("tick_60s", {})
    with open(DATA_DIR / "causes.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["cause_code", "cause_ru", "share_pct"])
        for k, v in sorted(oe.get("causes_pct", {}).items(), key=lambda kv: -kv[1]):
            w.writerow([k, CAUSE_RU.get(k, k), v])
    with open(DATA_DIR / "horizon.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["metric", "value"])
        for k in ("forecasts_total", "share_lead_in_window", "coverage", "online_mae_model_s", "online_mae_baseline_s"):
            if k in oe:
                w.writerow([k, oe[k]])
    n = card["n_points"]
    with open(DATA_DIR / "data_overview.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["group", "points"])
        w.writerow(["реальные борта (13)", n["pool_real"]])
        w.writerow(["синтетические копии (26)", n["pool"] - n["pool_real"]])


def main() -> int:
    card = json.loads(CARD.read_text(encoding="utf-8"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(card), encoding="utf-8")
    write_data(card)
    print(f"written {OUT.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
