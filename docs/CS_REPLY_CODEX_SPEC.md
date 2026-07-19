# CS 回信功能(控制台直接回复买家)· Codex 规格

> 目标:客服在控制台消息详情里直接写回信点发送 → 控制台调 WP 出站中转(Claude 的插件 v1.1 提供)→ `wp_mail` 经站点既有邮件管道(WP Mail SMTP)送达买家。发件人 service@barongyekhna.com,送达链路已被验证邮件实战验证。
> 分工:Codex = 控制台后端(回复表/发送端点/线程化详情)+ 前端(会话线 UI + 回复框);Claude = WP 插件出站端点、env 注入、部署与端到端。
> 边界(v1):控制台只发不收——买家的再回复进 Titan 邮箱,不回流控制台(IMAP 二期)。UI 上在回复框下注一行小字说明。

## 1. 数据模型 + 迁移
表 `cs_replies`:
- id UUID pk;`message_id` FK → cs_messages(索引)
- `body` text(1..10000,存纯文本)
- `sent_by` 用户标识(现有 user 体系)
- `delivery_status` enum:`sent` | `failed`
- `provider_note`(<=300,失败原因摘要,可空)
- created_at
迁移铁律照旧:单链分叉、不自动跑(Claude 手动执行)。

## 2. 发送端点(控制台登录态)
`POST /api/app/cs/messages/{id}/reply`,body `{"body":"..."}`,权限 `cs.customer_service.update`:
- 取原消息(含 channel/email/name);拼出站请求调 **WP 出站中转**:
  - URL 来自环境变量 `CS_WP_SEND_URL`(Claude 注入,值为 `https://barongyekhna.com/wp-json/barong-cs/v1/send`)
  - 头 `X-BY-CS-KEY` = 既有 `CS_INBOUND_KEY`(两端共用一把钥匙)
  - payload:`{"to_email","to_name","subject","body_text","channel"}`
  - subject 规则:`Re: Your message to Barong Yekhna`(B 端:`Re: Your wholesale inquiry — Barong Yekhna`)
- WP 返 2xx `{"ok":true}` → 存 reply 行(sent)+ 原消息 status 若为 new 自动流转 `in_progress`;非 2xx/超时 → 存 failed + provider_note,HTTP 502 给前端(错误信息可读)。
- 超时 15s;**不重试**(客服看到失败自己再点,避免双发)。
- fail-safe:发送失败绝不影响原消息数据。

## 3. 详情线程化
- `GET /api/app/cs/messages/{id}` 响应加 `replies: [...]`(升序)。
- 列表接口不带 replies(保持轻)。

## 4. 前端(消息详情 → 会话线)
- 详情抽屉/页改为**会话线**:买家原始消息气泡(左)→ 每条回复气泡(右,带发送时间与 sent/failed 徽章;failed 红标可见 provider_note)。
- 底部**回复框**:多行输入 + 「发送回复」按钮(发送中 loading、成功后清空并追加气泡);失败 toast + 气泡红标。
- 回复框下小字:「买家的回信会送达 service@ 邮箱(Titan),暂不回流控制台」。
- 新增路径登记前端代理白名单(契约测试会抓)。

## 5. 测试
- 后端:成功链路(mock WP 200)存行+状态流转;WP 超时/500 → failed 行 + 502;body 长度校验;权限。
- 前端 `npm test -- --run` 全绿。

## 硬约束
- 别动 Claude 的 WP 插件文件(backend/app/modules/p_series/wordpress/plugins/ 下的 php 归 Claude);别动 F。
- `bash scripts/run_backend_tests.sh unit` 全绿;每任务一句说明。

## 交付后 Claude 接管
env 注入 → 手动迁移 → 发版 → 端到端:控制台对 E2E 消息发一条回信 → WP 邮件窃听器(by-ev-maillog)确认出站 → 线程/状态/徽章全验。
