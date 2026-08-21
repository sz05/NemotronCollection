# Backend-only image for the split deployment: FastAPI API on Coolify, React
# frontend deployed separately on Vercel. (The old combined image built the
# frontend in here too; not needed when Vercel serves it.)
#
# Embeddings run on fastembed (ONNX Runtime), so there is no torch and no
# libgomp1 — the image is ~700MB instead of multiple GB.

FROM python:3.12-slim
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir --upgrade pip
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY main.py .

# Pre-download the embedding model (all-MiniLM-L6-v2 ONNX, ~90MB) into the
# image so the first /chat pays no network round-trip or cold-start download.
# Keep this id in sync with `embedding_model` in app/config.py.
ENV FASTEMBED_CACHE_PATH=/app/.cache/fastembed
RUN python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='sentence-transformers/all-MiniLM-L6-v2')"

# Proof-upload storage (PROOF_UPLOAD_DIR in app/config.py). Mount a Coolify
# persistent volume here in prod — local disk is wiped on every redeploy.
RUN mkdir -p /app/uploads

# Never run as root. appuser owns /app so uploads and the model cache are
# writable/readable at runtime.
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

ENV PORT=8000
EXPOSE 8000

# main.py mounts ./static only if it exists; in this split image it doesn't,
# so the app is API-only. init_db() + model warmup run on startup; /health
# returns immediately regardless.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
