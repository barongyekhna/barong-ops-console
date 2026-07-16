FROM python:3.12.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN python -m pip install --no-cache-dir -r backend/requirements.txt \
    && python -m playwright install --with-deps chromium \
    && apt-get update \
    && apt-get install --yes --no-install-recommends fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /app app \
    && mkdir -p /var/lib/barong/i-media /var/lib/barong/k-media /var/lib/barong/f-media \
    && chown -R app:app /app /var/lib/barong /ms-playwright

COPY --chown=app:app backend ./backend
COPY --chown=app:app r_system_v2 ./r_system_v2
COPY --chown=app:app tests/backend ./tests/backend
COPY --chown=app:app tests/fixtures ./tests/fixtures

USER app

EXPOSE 8000

CMD ["sh", "-c", "gunicorn backend.app.main:app --bind 0.0.0.0:8000 --workers ${GUNICORN_WORKERS:-2} --worker-class uvicorn.workers.UvicornWorker --timeout ${GUNICORN_TIMEOUT:-120} --graceful-timeout ${GUNICORN_GRACEFUL_TIMEOUT:-30} --access-logfile - --error-logfile - --forwarded-allow-ips='*'"]
