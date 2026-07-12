FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/srv

WORKDIR /srv

COPY c19_asset_service/requirements.txt /tmp/c19-asset-requirements.txt
RUN pip install --no-cache-dir -r /tmp/c19-asset-requirements.txt \
    && groupadd --system --gid 10001 c19asset \
    && useradd --system --uid 10001 --gid 10001 --home-dir /srv c19asset

COPY c19_asset_service /srv/c19_asset_service
RUN chown -R c19asset:c19asset /srv

USER c19asset

CMD ["python", "-m", "c19_asset_service.start", "api"]
