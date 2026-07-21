FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY alembic.ini ./
COPY alembic/ ./alembic/
# curated one-time entity merges (data/ is otherwise runtime-only and ignored)
COPY data/entity_merges_2026_07.json ./data/
ENV PYTHONPATH=/app/src

CMD ["python", "-m", "councilhound.cli", "--help"]
