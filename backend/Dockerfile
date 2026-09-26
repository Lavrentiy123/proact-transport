# Сборка из корня репозитория: docker build -f backend/Dockerfile -t proact-backend .
# Контекст ограничен файлом backend/Dockerfile.dockerignore (образ эмулятора и прочее в контекст не идут).
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY contracts/ contracts/
COPY features/ features/
# Плановое расписание (факты прибытия backend не читает: features.load_schedule их отбрасывает)
# и телеметрия дня для replay и пар unit_id ↔ tr_id.
COPY data/test/schedule.csv data/test/traffic.csv data/test/
COPY backend/ backend/
RUN useradd -m app
USER app
EXPOSE 8000 9201
HEALTHCHECK --interval=5s --timeout=3s --start-period=10s --retries=20 CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/ready').status==200 else 1)"
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
