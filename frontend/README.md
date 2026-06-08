# Frontend

The F09 frontend is a Next.js, React, and TypeScript console shell. It provides
the public `/login` page, authenticated navigation, the Dashboard, and
structured empty states for the remaining foundation routes.

Authentication uses the F08 backend endpoints through a restricted same-origin
Next.js proxy:

- `POST /auth/login`
- `GET /auth/me`
- `POST /auth/logout`

The proxy only accepts these three paths. It exists because the browser and
backend use separate local ports, while the F08 backend remains unchanged.
There is no public account creation flow and no business API integration.

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
