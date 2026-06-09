# C01 Production Deployment

This document prepares Barong Ops Console for formal production deployment on
`ops.barongyekhna.com`. It is a deployment plan and safety checklist; C01B-1
does not start production services, install Nginx files, issue certificates,
or connect real business systems.

## C01A Audit Result

C01A accepted the current repository as an empty foundation:

- FastAPI backend, PostgreSQL/Alembic, owner authentication, Next.js shell,
  F10 foundation APIs, F11 Foundation Demo, and F12 n8n Test Bridge exist.
- The foundation/demo loops do not represent real business completion.
- No real P-series workflow, production n8n workflow, WooCommerce, MinIO,
  Filebrowser, product task, product page automation, or AI model execution is
  connected.
- Production deployment may expose the console shell only after secrets,
  owner bootstrap, Nginx, HTTPS, and login acceptance are reviewed.

## DNS

DNS is confirmed before this deployment plan:

```text
ops.barongyekhna.com -> 45.76.175.217
```

## Production Compose Architecture

`docker-compose.production.yml` defines a standalone project surface:

- `console_frontend`: Next.js runtime, bound to `127.0.0.1:3000:3000`.
- `console_backend`: FastAPI runtime, bound to `127.0.0.1:8000:8000`.
- `console_postgres`: private PostgreSQL service on compose network port
  `5432` only, with no host port binding.
- `barong-ops-console-prod`: dedicated compose network.
- `console_postgres_data`: dedicated PostgreSQL volume.

Service names intentionally avoid existing n8n, barong, b013, filebrowser,
minio, serpbear, and baisuwan-agent names. The compose file uses
`env_file: .env.production`; the real file stays server-local.

## Create The Env File

On the production server only:

```bash
cp .env.production.example .env.production
chmod 600 .env.production
```

Edit every `CHANGE-ME` placeholder locally on the server. Do not commit,
paste, or print `.env.production`.

Required values:

- `APP_ENV=production`
- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`
- `DATABASE_URL=postgresql+psycopg://...@console_postgres:5432/...`
- `AUTH_TOKEN_SECRET`
- `OWNER_USERNAME`
- `OWNER_PASSWORD`
- `BACKEND_API_URL=http://console_backend:8000`
- `NEXT_PUBLIC_API_BASE_URL=https://ops.barongyekhna.com`
- `N8N_TEST_WEBHOOK_URL=`
- `N8N_TEST_CALLBACK_SECRET=`

`POSTGRES_PASSWORD` and the password embedded in `DATABASE_URL` must match.
URL-encode special characters in `DATABASE_URL`.

## Generate Secrets

Use strong random values and keep them on the server only:

```bash
openssl rand -base64 48
```

Use a unique value for `AUTH_TOKEN_SECRET`. It must be strong random material,
not a phrase, old password, or copied example value.

Use a separate strong password for `POSTGRES_PASSWORD`. Use a separate strong
temporary value for `OWNER_PASSWORD`.

## Bootstrap The Owner

`OWNER_PASSWORD` is only for first bootstrap. A reviewed production start
sequence is:

```bash
docker-compose -f docker-compose.production.yml build
docker-compose -f docker-compose.production.yml up -d console_postgres
docker-compose -f docker-compose.production.yml run --rm console_backend \
  python -m alembic -c backend/alembic.ini upgrade head
docker-compose -f docker-compose.production.yml run --rm console_backend \
  python -m backend.app.cli.bootstrap_owner
```

After the owner exists, edit the server-local `.env.production` and clear
`OWNER_PASSWORD`:

```text
OWNER_PASSWORD=
```

Then recreate only the console backend/frontend so the bootstrap password is
not kept in their runtime environment:

```bash
docker-compose -f docker-compose.production.yml up -d --force-recreate \
  console_backend console_frontend
```

## Start Production Compose

After env review, migration, and owner bootstrap:

```bash
docker-compose -f docker-compose.production.yml up -d \
  console_postgres console_backend console_frontend
```

Do not use this compose file to connect real P-series, production n8n,
WooCommerce, MinIO, or Filebrowser services during C01B.

## Configure Nginx

Use `deploy/nginx/ops.barongyekhna.com.conf.template` as a review template
only. It is not installed automatically.

Deployment operator steps after review:

1. Copy the template to the appropriate Nginx site path.
2. Replace placeholder certificate paths and ACME webroot paths.
3. Confirm it does not overwrite or edit existing n8n, files, MinIO, robot, or
   other production vhosts.
4. Validate with `nginx -t`.
5. Reload Nginx only after validation and approval.

The 443 server proxies to `http://127.0.0.1:3000`. The backend remains
private behind the frontend's restricted same-origin proxy and local loopback
binding.

## Request HTTPS

Request certificates only after Nginx config review. Example approaches:

```bash
certbot certonly --webroot \
  -w /var/www/letsencrypt-placeholder \
  -d ops.barongyekhna.com
```

or a reviewed Nginx plugin flow. Replace placeholder paths with the approved
server paths. Do not issue certificates as part of C01B-1.

## Login Acceptance

After production services, Nginx, and HTTPS are approved and started:

1. Open `https://ops.barongyekhna.com/login`.
2. Log in with `OWNER_USERNAME` and the bootstrap owner password.
3. Confirm `/dashboard` loads after login.
4. Confirm `/foundation-demo` and `/n8n-test` are present but remain
   demo/test-only.
5. Confirm `N8N_TEST_WEBHOOK_URL` is empty unless a separate approved test
   workflow exists.
6. Confirm no real P-series, n8n production workflow, WooCommerce, MinIO, or
   Filebrowser action occurs.

## Static File Check

Before starting production:

```bash
./scripts/check_production_deploy_files.sh
```

The script validates required files and compose syntax without starting
services or contacting external systems.

## Rollback

Rollback must affect only Barong Ops Console:

- Revert the Nginx vhost change for `ops.barongyekhna.com` and reload Nginx
  after `nginx -t`.
- Stop only `console_frontend` and `console_backend` if the console must be
  taken offline.
- Keep `console_postgres_data` unless a reviewed data rollback is required.
- Do not stop, restart, rename, or remove n8n, Filebrowser, MinIO,
  WooCommerce, robot, serpbear, b013, baisuwan-agent, or other production
  services.

## Protected Production Boundaries

C01B remains prohibited from:

- Modifying `/etc/nginx` or `/etc/caddy`.
- Issuing HTTPS certificates.
- Running production `docker-compose up/down`.
- Restarting, stopping, removing, or modifying production containers.
- Creating or committing a real `.env.production`.
- Reading or printing real secrets.
- Connecting real n8n, P-series, WooCommerce, MinIO, or Filebrowser.
- Modifying `/opt/n8n`, `/opt/filebrowser`, `/opt/minio`, or Docker data
  directories.

## Current Non-Integrations

The production deployment files expose only the console foundation. The system
still does not connect:

- Real P-series workflows.
- Real n8n production workflows.
- WooCommerce.
- MinIO.
- Filebrowser.
- Real product creation or publishing flows.
