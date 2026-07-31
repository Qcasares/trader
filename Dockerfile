# Single image, two entrypoints: the API and the worker (see docker-compose.yml).
FROM python:3.11-slim

WORKDIR /app

# Build deps for asyncpg; removed afterwards to keep the image small.
RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc libpq-dev \
 && rm -rf /var/lib/apt/lists/*

COPY requirements-engine.txt .
RUN pip install --no-cache-dir -r requirements-engine.txt \
 && apt-get purge -y gcc && apt-get autoremove -y

COPY src/ ./src/
COPY migrations/ ./migrations/
COPY config/ ./config/

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
