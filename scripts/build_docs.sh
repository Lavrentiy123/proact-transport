#!/usr/bin/env bash
# Документация по коду backend и пакета признаков features (pdoc) → docs/api/backend/index.html. Запуск из корня репозитория:
#   pip install -r backend/requirements-dev.txt && bash scripts/build_docs.sh
# Swagger/OpenAPI отдаёт сам сервис: http://localhost:8000/docs и /openapi.json.
set -euo pipefail
PY="${PYTHON:-python}"
rm -rf docs/api/backend
"$PY" -m pdoc -o docs/api/backend --docformat google backend features
"$PY" - <<'EOF'
import json
from backend.app.main import create_app
spec = create_app().openapi()
with open("docs/api/backend/openapi.json", "w", encoding="utf-8") as f:
    json.dump(spec, f, ensure_ascii=False, indent=1)
print("openapi paths:", len(spec["paths"]))
EOF
"$PY" scripts/sanitize_docs.py docs/api/backend   # без локального пути сборщика в значениях по умолчанию
echo "pdoc: docs/api/backend/index.html"
