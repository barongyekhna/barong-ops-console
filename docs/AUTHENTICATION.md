# 认证与访问控制

## 1. 第一版范围

登录认证属于空地基本体。第一版必须提供 `/login`，禁止公开注册，不提供公开注册页面或公开注册 API。

系统只允许通过受控初始化流程创建首个 `owner` 账号。初始化流程不得把默认密码、明文密码或真实密钥写入代码仓库。

第一版可以在模型和授权合同中预留 `admin`、`operator`、`viewer` 角色，但只启用 `owner`；其他角色在单独任务完成权限矩阵和测试前不得启用。

## 2. 用户数据

`users` 表最低字段：

| 字段 | 要求 |
| --- | --- |
| `id` | 用户唯一标识。 |
| `username` | 唯一、非空的登录名。 |
| `password_hash` | 非空的密码哈希，禁止存储或回传明文密码。 |
| `role` | 第一版有效值为 `owner`，预留其他角色。 |
| `is_active` | 账号是否允许登录。 |
| `created_at` | 创建时间。 |
| `updated_at` | 最近更新时间。 |
| `last_login_at` | 最近成功登录时间，可为空。 |

密码必须使用适合密码存储的强哈希算法和独立盐值。日志、错误、API 响应、Memory Event 和 Operation Log 均不得包含密码或密码哈希。

## 3. 认证 API

### `/auth/login`

- 接收受控的用户名和密码。
- 验证用户存在、`is_active` 为真且密码匹配。
- 登录成功后创建 server-side session，返回 `Set-Cookie`，并更新 `last_login_at`。
- 返回最低必要用户信息，不返回 `password_hash`、`access_token`、`token_type` 或 session id。
- 登录成功和失败都必须审计；失败响应不得泄露用户是否存在。

### `/auth/logout`

- 使当前 server-side session 失效，并清除浏览器 cookie。
- 重复退出或已失效 session 应清除 cookie，并返回安全的统一结果。
- 记录退出结果，不能只由前端删除本地状态。

### `/auth/me`

- 返回当前已认证用户的 `id`、`username`、`role`、`is_active` 等最低必要信息。
- 未认证、会话过期或会话失效时返回统一的未认证结果。
- 不返回认证秘密。

## 4. 页面保护

- `/login` 是第一版明确允许的公共页面。
- 未登录访问任何控制台页面必须跳转 `/login`。
- 登录后访问 `/login` 的行为由前端任务统一定义，不能形成循环跳转。
- 前端路由保护用于用户体验，后端 API 仍必须独立执行认证和授权。
- 用户被停用后不能建立新登录状态；已有 session 在下一次后端校验时失效。

`/health` 可以匿名访问，但不得泄露敏感配置。其他公共端点必须明确列入白名单，默认拒绝匿名访问。

## 5. 角色与权限

第一版 `owner` 拥有空地基管理权限，但仍必须遵守 Registry、Review、审计和外部写操作限制。`owner` 身份不能绕过日志，也不能使未注册模块运行。

预留角色含义：

- `admin`：后续受限系统管理角色。
- `operator`：后续任务操作和审核执行角色。
- `viewer`：后续只读观察角色。

上述角色第一版只预留，不启用，不允许通过直接修改请求字段获得。

## 6. 审计事件

以下事件必须写入 `operation_logs`：

- 登录成功。
- 登录失败。
- 主动退出和登录状态失效。
- 用户创建或 owner 初始化。
- 用户启用、停用和角色变化。
- 认证校验异常和可疑重复失败。

对系统安全状态、长期运行或后续决策有意义的事件，必要时同时写入 `memory_events`。Memory Event 不能替代 Operation Log。

审计记录应包含主体、动作、结果、时间、请求追踪标识和最低必要来源信息，但不得记录密码、`password_hash`、会话 token 或真实密钥。

## 7. 安全底线

- 禁止明文密码。
- 禁止公开注册。
- 禁止硬编码默认生产凭证。
- 禁止在 URL、日志或错误信息中传递认证秘密。
- 禁止把认证 token 或 session secret 暴露给前端 JavaScript。
- 浏览器认证状态只能通过 HttpOnly session cookie 承载。
- 禁止仅依赖前端隐藏页面实现授权。
- 禁止停用用户继续建立有效登录状态。
- 认证相关重要动作在日志落库失败时不得报告成功。

## 8. C16-FIX-2 Session 模式

C16-FIX-2 后，系统不再使用 localStorage JWT 作为浏览器认证载体。登录成功时后端创建 `auth_sessions` 记录，只把高熵 session id 写入 HttpOnly cookie；数据库只保存 session id 的 SHA-256 哈希。

`get_current_user()` 通过 `get_current_session()` 校验 cookie 中的 session id，检查 session 是否存在、是否过期、是否已吊销、用户是否仍存在且 `is_active=true`，然后再交给 RBAC/permission dependency。

默认 cookie 策略：

| 属性 | 默认值 |
| --- | --- |
| `HttpOnly` | `true` |
| `Secure` | `production` / `staging` 默认 `true`，开发默认 `false` |
| `SameSite` | `strict` |
| `Path` | `/api/backend` |
| `Max-Age` | `AUTH_SESSION_EXPIRE_MINUTES * 60` |

本地或直连后端测试可将 `AUTH_SESSION_COOKIE_PATH=/`，生产前端代理模式应保持 API path scope。
