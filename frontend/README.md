# Frontend

The frontend is a Next.js, React, and TypeScript console shell. F09 provides
the public `/login` page, authenticated navigation, the Dashboard, and
structured empty states for the remaining foundation routes.

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
