# C16-FIX-2 Session & Token Security Upgrade

## 1. Session Architecture Design

认证载体从 frontend-readable JWT 改为 server-side session：

- `auth_sessions` 表保存 session lifecycle 状态。
- 浏览器 cookie 保存原始 `session_id`，数据库只保存 `SHA-256(session_id)`。
- 前端 JavaScript 不读取、不保存、不拼接任何认证 secret。
- 后端每次请求通过 cookie 中的 `session_id` 查询服务端 session 状态。
- RBAC 继续从 `get_current_user()` 取得已认证用户，不改变业务路由授权接口。

核心文件：

- `backend/app/models/auth_session.py`
- `backend/app/services/auth_service.py`
- `backend/app/api/deps.py`
- `backend/app/core/session_cookies.py`
- `frontend/src/lib/api.ts`
- `frontend/src/app/api/backend/[...path]/route.ts`

## 2. Authentication Flow Diagram

```text
login form
  -> POST /api/backend/auth/login
  -> Next proxy forwards request to backend /auth/login
  -> backend verifies username/password
  -> backend creates auth_sessions row
  -> backend returns Set-Cookie: barong_ops_session=<session_id>; HttpOnly
  -> browser stores cookie under /api/backend

authenticated request
  -> frontend fetch(..., credentials: "include")
  -> browser sends cookie to /api/backend/*
  -> Next proxy forwards Cookie header to backend
  -> backend hashes session_id and validates auth_sessions row
  -> backend loads active user
  -> RBAC / permission dependency authorizes request

logout
  -> POST /api/backend/auth/logout
  -> backend invalidates auth_sessions row when valid
  -> backend returns delete-cookie header
  -> frontend clears local UI auth state
```

## 3. Cookie Configuration Spec

| Setting | Default | Requirement |
| --- | --- | --- |
| Cookie name | `barong_ops_session` | Contains opaque session id only. |
| `HttpOnly` | `true` | JS cannot read the authentication carrier. |
| `Secure` | `true` for `production` / `staging`, `false` for development unless overridden | Production cookies require HTTPS. |
| `SameSite` | `strict` | Cross-site request attachment is blocked by default. |
| `Path` | `/api/backend` | Browser only sends the cookie to the API proxy path. |
| `Max-Age` | `AUTH_SESSION_EXPIRE_MINUTES * 60` | Mirrors server-side session expiry. |

Direct-backend local tests may set `AUTH_SESSION_COOKIE_PATH=/`; frontend proxy deployments should keep `/api/backend`.

## 4. JWT to Session Migration Strategy

Phase 1 implemented in this fix:

- Removed frontend `localStorage` token usage.
- Removed frontend `accessToken` request option and Bearer header construction.
- Stopped returning `access_token` / `token_type` from `/auth/login`.
- Replaced backend JWT header parsing with cookie session validation.
- Added `auth_sessions` Alembic migration.
- Updated backend test helpers to use `Cookie: barong_ops_session=...`.
- Removed unused PyJWT backend dependency.

Phase 2 follow-up:

- Audit archived historical docs that still describe the former JWT phase.
- Add device/session management only if product requirements need user-visible active-session lists.

## 5. Middleware Integration Points

`backend/app/api/deps.py` is the integration boundary:

- `get_current_session()` reads `settings.auth_session_cookie_name`.
- It calls `validate_session()` from `auth_service`.
- `get_current_user()` returns `current_session.user`.
- `require_rbac()` and `require_permission()` keep their existing contracts and therefore integrate with C16-FIX-1 without business route rewrites.

The Next proxy no longer forwards `Authorization`; it forwards only `Cookie`, `Accept`, and `Content-Type`, then relays backend `Set-Cookie` responses.

## 6. Security Improvement Summary

- XSS cannot read the auth carrier because the cookie is HttpOnly.
- No auth token or session id is stored in `localStorage` or `sessionStorage`.
- The session cannot be forged without the high-entropy cookie value and a matching server-side row.
- Database storage uses session id hashes, not raw session ids.
- Logout invalidates the server-side session and clears the cookie.
- Expired and inactive-user sessions are rejected during backend validation.
- RBAC authorization remains server-side and is evaluated after session validation.

## 7. Post-Fix Risk Reduction Assessment

| Risk | Before | After |
| --- | --- | --- |
| XSS token theft | High: JWT was readable from `localStorage`. | Low: JS cannot read HttpOnly cookie. |
| Logout revocation | Weak: stateless JWT remained valid until expiry. | Strong: current session row is invalidated. |
| Session lifecycle control | Weak: expiry lived inside client-held JWT. | Strong: server validates expiry and invalidation state. |
| Token forgery | JWT depended on signing secret; leaked token was reusable. | Opaque high-entropy id must match server-side hash. |
| Frontend secret exposure | High: app code handled token values. | Low: app code never receives auth secret. |

Residual risks:

- SameSite strict reduces CSRF risk, but high-risk future write APIs may still need explicit CSRF tokens if cross-site embedding requirements change.
- Older historical docs may still describe the former JWT phase; current runtime docs and compose files use session settings.
- This fix does not implement user-facing active-session management or forced logout across all devices beyond normal server-side invalidation primitives.
