FROM python:3.12-slim-bookworm

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

COPY backend/app/requirements.txt /workspace/backend/app/requirements.txt
RUN python -m pip install --no-cache-dir \
    -r /workspace/backend/app/requirements.txt \
    pymupdf

COPY backend/app /workspace/backend/app

WORKDIR /workspace/backend
CMD ["python", "-m", "app.infrastructure.database.init_db"]
