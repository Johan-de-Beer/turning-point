FROM python:3.12-slim@sha256:02108f5d322dd89f1c9e552442c25acb0543dfdbc455693a5599624f20d9155d
WORKDIR /app
COPY backend/requirements.txt backend/requirements.lock.txt /app/backend/
RUN pip install --no-cache-dir -r backend/requirements.txt -c backend/requirements.lock.txt
COPY backend /app/backend
COPY server_data /app/server_data
RUN groupadd --gid 10001 replay && useradd --uid 10001 --gid 10001 --no-create-home replay \
    && mkdir -p /data && chown replay:replay /data
ENV PROVIDER=mock DATABASE_PATH=/data/turning-point.sqlite3 MICROSOFT_INFERENCE_APPROVED=false PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER replay
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
