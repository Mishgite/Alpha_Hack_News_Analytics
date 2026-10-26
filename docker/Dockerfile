FROM python:3.12.7-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/workspace/backend

WORKDIR /workspace

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-rus \
    && rm -rf /var/lib/apt/lists/*

COPY backend/app/requirements.lock /workspace/backend/app/requirements.lock
RUN python -m pip install --no-cache-dir --require-hashes \
    -r /workspace/backend/app/requirements.lock

COPY backend/app /workspace/backend/app

WORKDIR /workspace/backend
CMD ["python", "-m", "app.infrastructure.database.init_db"]
