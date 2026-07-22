# H 站点健康 · WP 桥(跳转管理 + 插件哨兵)· Codex 规格 v1

> 目标:把独立站瘦插件的可操作面接进控制台,老板自己点按钮,不再喊 Claude。
> 两块 UI 都长在**现有 H 站点健康模块**里(侧边栏白名单已有 `h`,零风险;F 一个字符不碰)。
> 分工:Codex = 后端 WP 桥 + H 端点 + 前端两标签页 + 测试;Claude = WP 凭据入密钥管理、生产发版(会挑老板上品的空档)、端到端验收。

## 0. 背景事实(已核实,直接引用)
- 站点 WP REST 凭据现于 `.env.production`:`WP_BASE_URL` / `WP_APP_USER` / `WP_APP_PASSWORD`(Basic Auth,能读写 /wp/v2/*)。
- 跳转表插件已注册 REST 选项 `barong_redirect_map`(JSON 字符串:`{"/旧路径": "/新路径", ...}`),写入即生效,**插件只在 404 时应用**——UI 手滑也劫持不了正常页面(自愈兜底)。
- 各插件诊断口(GET,无需登录,密钥=WP 选项 `barong_cs_key`,其值等于 env `CS_INBOUND_KEY`):
  `?by-rd-ping=<key>`(redirects)、`?by-eb-ping=<key>`(email-brand)、`?by-pf-ping=<key>`(perf)、`?by-rg-ping=<key>`(related)、`?by-track-ping=<key>`(track)、`?by-ev-ping`(email-verify,无密钥版本号)、`?by-ev-maillog`(邮件日志 JSON)、`?by-ev-smtpdiag=<key>`(真实 SMTP 登录体检,**重操作**)。
- 全部插件的版本/状态一把抓:`GET /wp-json/wp/v2/plugins`(Basic Auth)。

## 1. 后端:`backend/app/services/wp_bridge.py`(全后端唯一 WP 凭据持有者)
- 凭据解析顺序:①密钥管理(在 `r_system_v2/core/secret_manager.py` 的 `SERVICE_BINDING_CANDIDATES` 增加服务名 `wordpress`,绑定候选挂 H 模块;值为 JSON `{"base_url","user","app_password"}`)→ ②env 回退(`WP_BASE_URL`/`WP_APP_USER`/`WP_APP_PASSWORD`)。Claude 负责生产建 key 记录与绑定;回退保证过渡期零中断。
- **选项白名单硬编码**:v1 仅 `barong_redirect_map` 可读写。任何白名单外的选项名 → 直接抛错。这是本桥的第一护栏。
- 函数:`get_option(name)` / `set_option(name, value)`(经 `/wp/v2/settings`)、`fetch_plugins()`、`fetch_ping(slug)`(拼诊断 URL,密钥从 env `CS_INBOUND_KEY` 读)、`fetch_maillog()`。
- 出网超时 10s;WP 不可达返回结构化降级(`{"reachable": false, ...}`),**绝不让 H 页面 500**。

## 2. H 端点(挂现有 `backend/app/modules/h_series/sitehealth/router.py`,沿用 `_require_h_permission` 既有权限键:读用 read 键,写用 manage/update 键——以现有代码为准)
- `GET /h/wp/redirects` → `{"reachable": true, "rules": [{"from": "/a", "to": "/b"}, ...]}`(解析 option JSON;损坏时返回空表+`parse_error` 字段,不炸)
- `PUT /h/wp/redirects` → body `{"rules": [{"from","to"}, ...]}`,整表覆盖写回:
  - 校验:from 必须以 `/` 开头(允许带查询串如 `/?page_id=1759`);to 必须以 `/` 开头**或**是 `https://barongyekhna.com/...`(其它域一律 422——防开放跳转);两端 trim;from 去重(后者胜);≤200 条;单条 from ≤500 字符
- `POST /h/wp/redirects/verify` → body `{"path": "/x"}`:服务端向 `WP_BASE_URL + path` 发一次**不跟随**的 GET,返回 `{"status": 301, "location": "..."}`。path 必须以 `/` 开头,host 强制拼站点域——**杜绝 SSRF**
- `GET /h/wp/sentinel` → 一屏聚合:
  - `plugins`: 全部插件的 `{plugin, name, status, version}`(来自 /wp/v2/plugins)
  - `pings`: 上述 6 个诊断口的 `{slug, ok, version}`(逐个打,单个失败不拖累整体)
  - `mail`: maillog 最近 5 条 `{time, to, subject}` + `recent_failures`(to=="FAILED" 计数)
- `POST /h/wp/smtp-check` → 显式按钮才触发 `by-ev-smtpdiag`(**每次点击=一次真实 SMTP 登录,严禁自动轮询**——邮箱曾因高频登录被服务商封锁,历史事故)。返回体检 JSON 原文的关键字段(probe/verdict_line/host/username;**password_masked 不透传前端**)

## 3. 前端(`/h-site-health` 页,现有模块内加两个标签页)
- **「跳转管理」**:规则表格(旧路径/新目标/操作列)+ 行内编辑 + 「添加规则」+「保存」(整表 PUT)+ 每行「验证」按钮(调 verify,行内展示 `301 → /shop-2/` 或红色异常)。保存成功 toast;解析损坏时黄条提示
- **「插件哨兵」**:插件卡片墙(名称/版本/状态绿灰点)+ ping 状态 + 邮件区(最近 5 封 + 失败计数,失败>0 红标)+「SMTP 体检」按钮(带确认弹层,注明"将执行一次真实邮箱登录")
- 风格走 command-center 家规;新 API 路径**登记前端代理白名单**(契约测试会抓)
- 空态/降级:WP 不可达时两个标签页都显示「站点桥断开」卡片,不白屏

## 4. 测试
- 后端:白名单拦截(set_option 碰非白名单选项抛错)、跳转校验矩阵(坏 from/外域 to/超长/去重)、verify 的 SSRF 锁(path 不以 / 开头 422;host 不可被 body 覆盖)、WP 不可达降级形状、smtp-check 不在 sentinel 里被调用(哨兵接口源码断言不含 smtpdiag)。`bash scripts/run_backend_tests.sh unit` 全绿
- 前端:`npm test -- --run` 全绿(含代理白名单)

## 硬约束
- **无迁移、不建表**(v1 无需持久化,数据源都在 WP 侧)
- 别动 Claude 的插件目录(backend/app/modules/p_series/wordpress/plugins/);别动 F;secret_manager 的改动仅限新增 `wordpress` 服务名条目,不碰既有服务
- 每任务一句根因/做法;本地提交,测试绿

## 交付后 Claude 接管
WP 凭据 JSON 入密钥管理 + 模块绑定 → 挑老板上品空档发版(后端+前端)→ E2E:UI 加一条跳转→站点验证 301→哨兵全绿→SMTP 体检按钮实测 → 交老板验收。
