# Сборка из корня репозитория: docker build -f ml_core/Dockerfile -t proact-ml-core .
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY ml_core/requirements.txt ml_core/requirements-nodeps.txt ml_core/
RUN pip install --no-cache-dir -r ml_core/requirements.txt  && pip install --no-cache-dir --no-deps -r ml_core/requirements-nodeps.txt
COPY contracts/ contracts/
COPY features/ features/
COPY models/ models/
COPY ml_core/ ml_core/
RUN useradd -m app
USER app
EXPOSE 8001
HEALTHCHECK --interval=10s --timeout=3s --retries=5 CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8001/ready').status==200 else 1)"
CMD ["uvicorn", "ml_core.app.main:app", "--host", "0.0.0.0", "--port", "8001"]
