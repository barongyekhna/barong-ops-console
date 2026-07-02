FROM python:3.12.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN python -m pip install --no-cache-dir -r backend/requirements.txt \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /app app \
    && mkdir -p /var/lib/barong/i-media /var/lib/barong/k-media \
    && chown -R app:app /app /var/lib/barong

COPY --chown=app:app backend ./backend
COPY --chown=app:app r_system_v2 ./r_system_v2
COPY --chown=app:app tests/backend ./tests/backend

USER app

EXPOSE 8000

CMD ["sh", "-c", "gunicorn backend.app.main:app --bind 0.0.0.0:8000 --workers ${GUNICORN_WORKERS:-2} --worker-class uvicorn.workers.UvicornWorker --timeout ${GUNICORN_TIMEOUT:-120} --graceful-timeout ${GUNICORN_GRACEFUL_TIMEOUT:-30} --access-logfile - --error-logfile - --forwarded-allow-ips='*'"]
