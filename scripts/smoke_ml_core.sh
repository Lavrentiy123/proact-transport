#!/usr/bin/env bash
# Smoke ml-core в Docker: сборка → запуск → /ready (до 60 с) → /v1/predict на 2 строках → удаление.
# Запуск из корня репозитория: bash scripts/smoke_ml_core.sh [порт, по умолчанию 8001]
set -euo pipefail
PORT="${1:-8001}"
IMG=proact-ml-core
NAME=mlc
cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

t0=$(date +%s)
docker build -f ml_core/Dockerfile -t "$IMG" . >/tmp/mlc_build.log 2>&1 || { tail -30 /tmp/mlc_build.log; exit 1; }
echo "build: $(( $(date +%s) - t0 )) s"
echo "image size: $(docker image inspect "$IMG" --format '{{.Size}}' | awk '{printf "%.0f MB", $1/1024/1024}')"

cleanup
t1=$(date +%s)
docker run -d --name "$NAME" -p "$PORT:8001" "$IMG" >/dev/null
for i in $(seq 1 60); do
  if curl -fs "http://localhost:$PORT/ready" >/dev/null 2>&1; then
    echo "ready after $(( $(date +%s) - t1 )) s"
    break
  fi
  if [ "$i" = 60 ]; then echo "NOT READY in 60 s"; docker logs "$NAME" | tail -30; exit 1; fi
  sleep 1
done

BODY='{"model":"online","rows":[
 {"tr_id":131672,"features":{"cur_dev_s":120,"horizon_s":720,"hour":8,"n_stops_between":6,"since_last_plan_s":60,"rdev_last":120,"rdev_age_s":30,"n_pending":0,"lb_delay_s":0,"tel_age_s":5,"last_speed":18,"v_mean_5m":14,"stop_ratio_5m":0.3,"dist_to_target_m":2500,"route_dist_m":3000,"proj_delay_s":60}},
 {"tr_id":122048,"features":{"cur_dev_s":-30,"horizon_s":660,"hour":17,"tel_age_s":null}}]}'
RESP=$(curl -fs -X POST "http://localhost:$PORT/v1/predict" -H 'Content-Type: application/json' -d "$BODY")
echo "predict: $RESP" | cut -c1-400
echo "$RESP" | grep -q '"results":\[{' && echo "SMOKE OK" || { echo "SMOKE FAIL"; exit 1; }
