#!/usr/bin/env bash
# Smoke всей системы: docker compose up --build -d → /ready ≤ 120 с → /api/v1/alerts → время холодного старта.
# Запуск из корня репозитория: bash scripts/smoke.sh [порт backend, по умолчанию 8000]
set -euo pipefail
PORT="${1:-${BACKEND_PORT:-8000}}"
URL="http://localhost:${PORT}"

t0=$(date +%s)
docker compose up --build -d
t_up=$(date +%s)
echo "compose up --build -d: $((t_up - t0)) s"

ready=""
for _ in $(seq 1 120); do
  if [ "$(curl -s -o /dev/null -w '%{http_code}' "${URL}/ready" || true)" = "200" ]; then ready=1; break; fi
  sleep 1
done
t_ready=$(date +%s)
if [ -z "$ready" ]; then
  echo "FAIL: ${URL}/ready не ответил 200 за 120 с"; docker compose ps; docker compose logs --tail 50 backend; exit 1
fi
echo "cold start: up→/ready $((t_ready - t_up)) s (всего с начала сборки $((t_ready - t0)) s)"
curl -s "${URL}/api/v1/system/status"; echo
echo "alerts: $(curl -s "${URL}/api/v1/alerts" | head -c 300)"
echo "SMOKE OK"
