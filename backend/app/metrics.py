"""``GET /metrics`` — текст в формате Prometheus (без внешних библиотек).

Квантили ``tick_duration_ms`` и ``infer_ms`` считаются по последним 2000 тикам.
"""

from __future__ import annotations

import numpy as np


def _q(values, q: float) -> float | None:
    if not values:
        return None
    return float(np.percentile(np.asarray(values, dtype=np.float64), q * 100))


class _Out:
    def __init__(self):
        self.lines: list[str] = []

    def metric(self, name: str, kind: str, help_: str, samples: list[tuple[str, float | None]]) -> None:
        self.lines.append(f"# HELP {name} {help_}")
        self.lines.append(f"# TYPE {name} {kind}")
        for labels, v in samples:
            if v is None:
                continue
            self.lines.append(f"{name}{labels} {float(v):.6g}")

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"


def render(hub, broadcaster=None) -> str:
    """Метрики живого режима (для заглушки — только WebSocket)."""
    o = _Out()
    if broadcaster is not None:
        o.metric("ws_clients", "gauge", "Подключённых клиентов WebSocket /ws/live", [("", len(broadcaster.clients))])
        o.metric("ws_messages_sent_total", "counter", "Отправлено снапшотов", [("", broadcaster.sent)])
    srv = getattr(hub, "server", None)
    if srv is None:
        o.metric("backend_stub", "gauge", "1 — backend в режиме заглушки (BACKEND_STUB=1)", [("", 1)])
        return o.text()
    st = srv.stats
    o.metric("ndtp_sessions", "gauge", "Открытых TCP-сессий NDTP", [("", srv.sessions)])
    o.metric("ndtp_connections_total", "counter", "Принятых TCP-подключений", [("", srv.connections_total)])
    o.metric("ndtp_packets_total", "counter", "Принятых realtime-пакетов NDTP", [("", srv.realtime_packets)])
    o.metric("ndtp_nav_fixes_total", "counter", "Навигационных ячеек G6CellNav00", [("", srv.nav_fixes)])
    o.metric("ndtp_handshakes_total", "counter", "Пакетов NPH_SGC_CONN_REQUEST", [("", srv.handshakes)])
    o.metric("ndtp_crc_errors_total", "counter", "Кадров с неверным CRC (отброшены)", [("", st.crc_errors)])
    o.metric("ndtp_garbage_bytes_total", "counter", "Байт вне кадров (ресинхронизация)", [("", st.garbage_bytes)])
    o.metric("ndtp_last_packet_age_seconds", "gauge", "Секунд с последнего пакета (реальное время)",
             [("", hub.last_packet_age_s())])
    late = sum(v.online.n_dropped_late for v in hub.fleet.scheduled()) if hub.fleet else 0
    ws_drop = broadcaster.dropped if broadcaster is not None else 0
    o.metric("dropped_total", "counter", "Отброшено: вне окна времени / старше буфера борта / вытеснено у медленного WS",
             [('{kind="out_of_window"}', hub.dropped_out_of_window), ('{kind="late_beyond_buffer"}', late),
              ('{kind="ws_slow_client"}', ws_drop)])
    mode = hub.mode().value
    o.metric("backend_mode", "gauge", "Режим: 1 у текущего", [(f'{{mode="{m}"}}', 1 if m == mode else 0)
                                                                 for m in ("LIVE", "DEGRADED", "REPLAY")])
    o.metric("sim_time_seconds", "gauge", "Время симуляции (секунды времени датасета как UTC)", [("", hub.clock.now_s())])
    o.metric("replay_speed", "gauge", "Скорость симуляции относительно реального времени", [("", hub.clock.speed)])
    t = hub.ticker
    o.metric("tick_duration_ms", "summary", "Длительность тика прогнозов, мс (последние 2000)",
             [('{quantile="0.5"}', _q(t.tick_ms, 0.5)), ('{quantile="0.99"}', _q(t.tick_ms, 0.99)),
              ("_count", len(t.tick_ms))])
    o.metric("infer_ms", "summary", "Вызов ml-core /v1/predict на батч тика, мс (последние 2000)",
             [('{quantile="0.5"}', _q(t.infer_ms, 0.5)), ('{quantile="0.99"}', _q(t.infer_ms, 0.99)),
              ("_count", len(t.infer_ms))])
    o.metric("tick_total", "counter", "Выполнено тиков", [("", t.ticks)])
    o.metric("tick_overruns_total", "counter", "Тиков, не уложившихся в период", [("", t.overruns)])
    o.metric("tick_errors_total", "counter", "Тиков с ошибкой", [("", t.errors)])
    o.metric("tick_rows", "gauge", "Бортов в последнем батче прогноза", [("", t.last_rows)])
    ml = t.ml
    o.metric("ml_calls_total", "counter", "Вызовов ml-core", [("", ml.calls)])
    o.metric("ml_errors_total", "counter", "Ошибок вызова ml-core", [("", ml.errors)])
    o.metric("ml_breaker_open", "gauge", "1 — circuit breaker ml-core открыт (прогноз по правилу)",
             [("", 1 if ml.state == "open" else 0)])
    o.metric("forecasts_active", "gauge", "Бортов с прогнозом на 10–15 мин", [("", len(hub.forecasts))])
    o.metric("alerts_active", "gauge", "Активных алертов", [("", len(t.book.active))])
    o.metric("alerts_raised_total", "counter", "Поднято алертов", [("", t.book.raised_total)])
    h = t.journal.metrics()
    o.metric("journal_forecasts_total", "counter", "Прогнозов в журнале", [("", h.forecasts_total)])
    o.metric("journal_resolved_total", "counter", "Прогнозов, сверенных с прибытием (детектор)", [("", h.resolved_total)])
    o.metric("horizon_share_in_window", "gauge", "Доля прогнозов с lead ∈ [600, 900] с", [("", h.share_lead_in_window)])
    o.metric("online_mae_seconds", "gauge", "Онлайн-MAE на сверенных прогнозах",
             [('{model="forecast"}', h.online_mae_model_s), ('{model="baseline_cur_dev"}', h.online_mae_baseline_s)])
    return o.text()
