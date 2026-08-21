# Combined frontend + backend image: one FastAPI process serves the API and
# the built React static bundle on a single port. Three stages:
#   1. frontend-builder -- npm build (Vite bakes VITE_* vars in at build time)
#   2. backend-builder   -- Python deps into a venv (sentence-transformers
#      pulls in torch, so this is the heaviest/slowest layer -- kept separate
#      from app code so it's cached across code-only changes)
#   3. runtime            -- slim final image: venv + app code + frontend dist

FROM node:22-slim AS frontend-builder

WORKDIR /build

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install

COPY frontend/ .

# Left empty by default: the combined image serves the API and the static
# bundle from the same origin, so the frontend just calls same-origin
# relative paths (see normalizeBaseUrl in src/api/client.js) -- this works
# regardless of what hostname/port/protocol you actually browse to, unlike
# baking in a literal "http://localhost:8000" that only matches if you visit
# that exact origin. Only set this if the frontend needs to call a backend on
# a genuinely different origin (e.g. a split Vercel + Railway deployment).
ARG VITE_API_BASE_URL=
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN npm run build


FROM python:3.12-slim AS backend-builder

WORKDIR /build

RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the embedding model into the image so containers don't hit the
# network (or pay a multi-second cold start) on first /chat. Keep this model
# id in sync with `embedding_model` in app/config.py.
RUN python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"


FROM python:3.12-slim AS runtime

WORKDIR /app

# libgomp1: required by torch's CPU backend at import time.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=backend-builder /venv /venv
COPY --from=backend-builder /root/.cache/huggingface /root/.cache/huggingface
ENV PATH="/venv/bin:$PATH"

COPY app ./app
COPY main.py .
COPY --from=frontend-builder /build/dist ./static

# Proof-upload storage (see PROOF_UPLOAD_DIR in app/config.py). Mount a volume
# here in compose/prod -- local disk on most PaaS is ephemeral.
RUN mkdir -p /app/uploads

RUN useradd --create-home appuser \
    && chown -R appuser:appuser /app
USER appuser

ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
