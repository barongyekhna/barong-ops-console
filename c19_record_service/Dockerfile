FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/srv

WORKDIR /srv

COPY c19_record_service/requirements.txt /tmp/c19-record-requirements.txt
RUN pip install --no-cache-dir -r /tmp/c19-record-requirements.txt \
    && groupadd --system c19record \
    && useradd --system --gid c19record --home-dir /srv c19record

COPY c19_record_service /srv/c19_record_service
RUN chown -R c19record:c19record /srv

USER c19record

HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/healthz', timeout=2).read()"]

CMD ["python", "-m", "c19_record_service.start"]
