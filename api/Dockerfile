# Build context is the REPO ROOT (see fly.toml / docker-compose.yml) — the
# API imports the councilhound package from ingestion/src.
FROM python:3.12-slim

WORKDIR /app

COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the embedding model into the image so cold starts don't pull ~500MB
# from Hugging Face at boot.
ENV HF_HOME=/models
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-base-en-v1.5')"

COPY api/app/ ./app/
COPY ingestion/src/councilhound/ ./councilhound/

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
