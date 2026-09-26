#!/usr/bin/env bash
# Chaos-тест надёжности (критерий 5): обрыв потока NDTP и падение ml-core при работающей системе.
# Запуск из корня репозитория при поднятом `docker compose up -d`: bash scripts/chaos.sh [порт backend]
# Источник потока по умолчанию — сервис replay (для эмулятора: SOURCE=ndtp-emulator bash scripts/chaos.sh).
set -uo pipefail
PORT="${1:-${BACKEND_PORT:-8000}}"
URL="http://localhost:${PORT}"
SOURCE="${SOURCE:-replay}"

now() { date +%s.%N; }
since() { awk -v a="$1" -v b="$(now)" 'BEGIN{printf "%.1f", b-a}'; }
field() { curl -s "${URL}/api/v1/system/status" | grep -o "\"$1\":[^,}]*" | head -1 | cut -d: -f2- | tr -d '"'; }
qualities() { curl -s "${URL}/api/v1/vehicles" | grep -o '"quality":"[a-z]*"' | sort | uniq -c | tr '\n' ' '; }
wait_for() {  # wait_for <поле> <значение> <таймаут, с>
  local t0; t0=$(now)
  while awk -v a="$t0" -v b="$(now)" -v lim="$3" 'BEGIN{exit !(b-a < lim)}'; do
    [ "$(field "$1")" = "$2" ] && { since "$t0"; return 0; }
    sleep 0.2
  done
  echo "TIMEOUT"; return 1
}

echo "== исходно: mode=$(field mode) sessions=$(field ndtp_sessions) predictor=$(field predictor) | $(qualities)"
[ "$(field mode)" = "LIVE" ] || { echo "FAIL: система не в LIVE — сначала docker compose up -d и дождаться потока"; exit 1; }

echo "== 1. обрыв потока: docker compose stop ${SOURCE}"
docker compose stop "${SOURCE}" >/dev/null 2>&1
t_stop=$(now)
echo "   источник остановлен; жду DEGRADED..."
t_deg=$(wait_for mode DEGRADED 30)
echo "   DEGRADED через ${t_deg} с после остановки источника"
sleep 3
echo "   во время обрыва: /health=$(curl -s -o /dev/null -w '%{http_code}' "${URL}/health") sessions=$(field ndtp_sessions) predictor=$(field predictor) | $(qualities)"

echo "== 2. восстановление: docker compose start ${SOURCE}"
docker compose start "${SOURCE}" >/dev/null 2>&1
t_live=$(wait_for mode LIVE 30)
echo "   LIVE через ${t_live} с после запуска источника"
sleep 3
echo "   после восстановления: sessions=$(field ndtp_sessions) predictor=$(field predictor) | $(qualities)"

if [ "${WITH_ML:-1}" = "1" ]; then
  echo "== 3. падение ml-core: docker compose stop ml-core"
  docker compose stop ml-core >/dev/null 2>&1
  t_fb=$(wait_for predictor fallback-rule 30)
  echo "   прогноз по правилу через ${t_fb} с; /health=$(curl -s -o /dev/null -w '%{http_code}' "${URL}/health") | $(qualities)"
  docker compose start ml-core >/dev/null 2>&1
  t_ml=$(wait_for predictor ml-core 120)
  echo "   ml-core снова считает через ${t_ml} с после запуска (breaker half-open раз в 30 с)"
fi
echo "CHAOS DONE: degraded=${t_deg}s live=${t_live}s"
