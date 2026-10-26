FROM python:3.12-slim-bookworm AS backend
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PYTHONPATH=/workspace/backend
WORKDIR /workspace/backend
COPY backend/app/requirements.txt app/requirements.txt
RUN python -m pip install --no-cache-dir -r app/requirements.txt \
    && useradd --uid 10001 --create-home app \
    && mkdir -p /workspace/runtime \
    && chown app:app /workspace/runtime
COPY --chown=app:app backend/app app
COPY backend/data/examples/recent-news-2026-10-25.json data/examples/recent-news-2026-10-25.json
USER app
ENTRYPOINT ["python", "-m", "app.container"]
CMD ["api"]

FROM backend AS parser
USER root
RUN apt-get update \
    && apt-get install --no-install-recommends -y tesseract-ocr tesseract-ocr-eng tesseract-ocr-rus \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir pymupdf==1.26.7 openpyxl==3.1.5
USER app

FROM backend AS production
