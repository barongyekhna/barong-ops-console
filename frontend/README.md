# Frontend

The frontend is a Next.js, React, and TypeScript console shell. F09 provides
the public `/login` page, authenticated navigation, the Dashboard, and
structured empty states for the remaining foundation routes.

C01 production deployment is complete for
`https://ops.barongyekhna.com`. The production frontend service is
`console_frontend`, bound only to `127.0.0.1:3000` behind Nginx HTTPS reverse
proxy. HTTP redirects to HTTPS. It uses
`BACKEND_API_URL=http://console_backend:8000` for the server-side restricted
proxy. The deployment does not expose a generic backend proxy and does not
connect real business systems. C01 remains foundation/console only; C02 is
production/test environment separation.

C02C has started the staging/test frontend on `127.0.0.1:3100`. The staging
frontend service is `console_staging_frontend` and uses
`BACKEND_API_URL=http://console_staging_backend:8000` for the server-side
restricted proxy. The real `.env.staging` is not committed and must not reuse
production owner passwords or token secrets. C02D added read-only
dual-environment checks, C02E completed final production/staging acceptance,
and C02F sealed the environment isolation system. Both environments are usable
and isolated. Staging is still not exposed publicly, no real business
integration is connected, and the next stage is C03: Owner creates
sub-accounts.

F13 accepts the required routes `/`, `/login`, `/dashboard`,
`/foundation-demo`, `/n8n-test`, `/products`, `/modules`, `/agents`,
`/workflows`, `/jobs`, `/artifacts`, `/reviews`, `/errors`,
`/memory-events`, `/users`, and `/settings`. The console route group uses the
protected layout and authentication guard. There is no `/register` page.

Authentication uses the F08 backend endpoints through a restricted same-origin
Next.js proxy:

- `POST /auth/login`
- `GET /auth/me`
- `POST /auth/logout`

F10 extends the restricted same-origin proxy with GET-only access for:

- `/modules`
- `/agents`
- `/workflows`
- `/jobs`
- `/artifacts`
- `/reviews`
- `/errors`
- `/memory-events`

Those pages show loading, backend error, empty, and simple list states. The
proxy does not expose F10 write APIs to the UI. Products remains an empty
state and does not create product records. There is no public account creation
flow or real external integration.

F11 adds the protected `/foundation-demo` page. Its **Run Foundation Demo**
button calls only `POST /foundation-demo/run`, while initial/retry loading
calls only `GET /foundation-demo/latest`. The page displays the demo job ID and
status, event count, artifact title, review status, memory event summary, and
operation-log count.

The panel explicitly identifies the flow as an internal demo. It does not
trigger real n8n, WooCommerce, MinIO/Filebrowser, P-series tasks, external
HTTP calls, uploads, or real business work. The proxy allowlist exposes only
the two exact Foundation Demo paths and does not become a generic write proxy.

F12 adds the protected `/n8n-test` page. The **Run n8n Test** button calls only
`POST /n8n-test/run`; the page loads and polls `GET /n8n-test/latest` while a
Job is pending, running, or waiting for callback. It displays only the test
Job ID/status, latest event, demo Artifact/Review/Memory summary, operation-log
count, and safe error message.

The page states: “Test bridge only. Does not run real n8n production
workflows.” The restricted proxy exposes only the exact run and latest paths.
It does not proxy `/n8n-test/callback`, display callback credentials, or
provide a generic webhook route. F12 does not add registration, product
creation, WooCommerce, P-series, MinIO, or Filebrowser UI integration.

C03C adds the protected `/users` page under **User Management** in the System
navigation. C03E has released it to production at
`https://ops.barongyekhna.com/users`. It calls only the owner-only C03B
`/users` APIs through the restricted same-origin proxy. The page lists users,
creates `viewer`, `operator`, and `reviewer` accounts, shows user detail,
updates managed roles, enables/disables users, and resets sub-account
passwords with confirmation.
It does not show `owner` or `super_admin` as create options, does not add
public registration, does not print passwords or tokens, and does not connect
real business systems. C03D accepted this flow on staging with a
`c03d_test_<timestamp>` account, including list/detail, login, 403 for
non-owner `/users`, disable, enable, password reset, `role=owner` rejection,
`/auth/register` 404, and operation log verification. C03E production
read-only checks confirmed `/users` returns 200, unauthenticated
`/api/backend/users` returns 401, `/auth/register` still returns 404, and
production/staging/dual-env checks pass. C03 still does not add
`super_admin`, full RBAC, or real business integration. C03F has sealed this
stage; the next stage is C04: role system.

C04A has started the role-system stage with
`docs/C04_ROLE_SYSTEM_PLAN.md`. C04 is about account identity labels, not the
full permission system. C04B added the owner-only `GET /users/roles` catalog,
and C04C updates the `/users` page to read it through
`/api/backend/users/roles`.

The User Management create-user selector and managed-role selector are now
generated from catalog roles that are `assignable=true` and pass the frontend
safety whitelist. They currently show only `viewer`, `operator`, and
`reviewer`. The page also displays `owner`, `super_admin`, `module_admin`, and
`bot_agent` as reserved/not assignable in C04. `super_admin` is not enabled,
`module_admin` still needs module scope, and `bot_agent` still needs agent
identity and token scope design.

C04 does not make `super_admin` all-powerful, does not connect `bot_agent` to
real automation, and does not define module permissions. C05 will define
permissions, module access, and role-to-permission bindings. Future company
positions such as designer, SEO editor, customer service, or factory
supervisor should be represented through role plus later job title,
department, module access, and permissions, not as hard-coded frontend role
strings. C04C does not deploy staging/production, create real users, add
public registration, or connect real business systems. The next step is C04D:
staging test acceptance for the role catalog UI.

## Configuration

For host-based development, use the example backend URL:

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

The Docker example also sets `BACKEND_API_URL=http://backend:8000` for
container-to-container requests. `BACKEND_API_URL` takes precedence inside the
Next.js server. Neither variable may contain credentials.

## Docker verification

Do not install dependencies on the host. From the repository root, run:

```bash
./scripts/test_frontend_docker.sh
```

The frontend Docker build runs the route and safety verification, TypeScript
typecheck, and the production Next.js build before producing the runtime image.

Run the full repository acceptance with:

```bash
./scripts/test_foundation_acceptance.sh
```

## Temporary login preview

From the repository root, set example-only owner and token values, bootstrap
the named example project, and start the example backend/frontend:

```bash
export COMPOSE_PROJECT_NAME=barong-ops-console-preview
read -r -s -p "Preview token signing value (32+ bytes): " AUTH_TOKEN_SECRET
export AUTH_TOKEN_SECRET
export OWNER_USERNAME="preview_owner"
read -r -s -p "Preview owner password (12+ characters): " OWNER_PASSWORD
export OWNER_PASSWORD
./scripts/bootstrap_owner_docker.sh
docker-compose -p "$COMPOSE_PROJECT_NAME" \
  -f docker-compose.example.yml up --build backend frontend
```

Open `http://127.0.0.1:3000/login`. Leave `N8N_TEST_WEBHOOK_URL` and
`N8N_TEST_CALLBACK_SECRET` empty for a login-only preview. These settings and
`AUTH_TOKEN_SECRET` are environment variables; real values must not be
committed. This preview uses only `docker-compose.example.yml` and does not
connect production n8n, P-series, WooCommerce, MinIO, or Filebrowser services.
