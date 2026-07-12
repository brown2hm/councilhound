# Build context is the REPO ROOT (see docker-compose.yml) — the API imports
# the councilhound package from ingestion/src.
FROM python:3.12-slim

WORKDIR /app

COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api/app/ ./app/
COPY ingestion/src/councilhound/ ./councilhound/

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
