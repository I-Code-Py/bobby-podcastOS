FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /srv/app

COPY requirements.txt .
# --with-deps installe aussi les librairies système nécessaires à Chromium
# (Instagram est scrapé via un navigateur headless, pas d'API officielle).
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app

RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /srv/app/data \
    && chown -R appuser:appuser /srv/app /ms-playwright
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health', timeout=3).raise_for_status()"

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips '*'"]
