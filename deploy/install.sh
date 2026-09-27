#!/usr/bin/env bash
# Стенд «ПроАкт.Транспорт» на чистой Ubuntu 22.04/24.04 (ВМ Yandex Cloud): Docker → клон → docker compose up.
#
#   sudo bash install.sh            # ветка main
#   sudo bash install.sh v1.0       # тег после код-фриза (повторный запуск обновляет стенд на месте)
#
# Порты: дашборд 3000, backend + Swagger 8000, ml-core + Swagger 8001, NDTP (TCP) 9201.
# Поток по умолчанию — replay реального дня 06.01.2026 по NDTP, идёт по кругу (`--loop`), вмешательство не нужно.
set -euo pipefail

REF="${1:-main}"
REPO="https://github.com/Lavrentiy123/proact-transport.git"
DIR=/opt/proact

if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker
command -v git >/dev/null 2>&1 || { apt-get update -qq && apt-get install -y -qq git; }

# образ эмулятора (Git LFS, 134 МБ) стенду не нужен: поток — replay; git-lfs не ставим
if [ ! -d "$DIR/.git" ]; then
  GIT_LFS_SKIP_SMUDGE=1 git clone "$REPO" "$DIR"
fi
cd "$DIR"
GIT_LFS_SKIP_SMUDGE=1 git fetch --tags --force origin
if git rev-parse -q --verify "refs/tags/$REF" >/dev/null; then
  GIT_LFS_SKIP_SMUDGE=1 git checkout -f --detach "refs/tags/$REF"
else
  GIT_LFS_SKIP_SMUDGE=1 git checkout -f --detach "origin/$REF"
fi
echo "commit: $(git log --oneline -1)"

docker compose up --build -d

# ждём здоровья сервисов (первая сборка на 2 vCPU — 5–10 мин, дальше из кэша)
for i in $(seq 1 120); do
  if curl -fs http://localhost:8000/ready >/dev/null && curl -fs http://localhost:8001/ready >/dev/null \
     && curl -fs http://localhost:3000/ >/dev/null; then
    break
  fi
  sleep 5
done
docker compose ps
IP=$(curl -fs --max-time 5 https://ifconfig.me || hostname -I | awk '{print $1}')
echo
echo "Дашборд:        http://$IP:3000/"
echo "Swagger backend: http://$IP:8000/docs"
echo "Swagger ml-core: http://$IP:8001/docs"
echo "NDTP (эмулятор жюри): $IP:9201"
