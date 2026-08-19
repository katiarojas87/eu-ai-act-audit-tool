# EU AI Act audit tool — FastAPI backend with full RAG (ChromaDB + local e5
# embeddings). The UI is the Next.js app in web/, deployed separately.
# Builds the vector index at image-build time so cold starts are fast.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.hfcache

WORKDIR /app

# Build tools needed to compile some wheels (e.g. ChromaDB's hnswlib).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc g++ \
    && rm -rf /var/lib/apt/lists/*

# Install CPU-only torch first (much smaller than the default CUDA build),
# then the rest of the requirements.
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install -r requirements.txt

# App code (law text in data/ and knowledge/ are committed and needed by ingest).
COPY . .

# Pre-build the ChromaDB index + cache the embedding model into the image.
RUN python src/ingest.py

# Cloud Run sends the port to listen on via $PORT (defaults to 8080).
EXPOSE 8080
# v2 backend: FastAPI (deterministic rule engine + RAG-grounded fact extraction).
CMD uvicorn api:app --app-dir src --host 0.0.0.0 --port ${PORT:-8080}
