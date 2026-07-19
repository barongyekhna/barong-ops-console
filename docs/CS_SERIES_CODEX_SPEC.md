# CS 系列(Customer Service 客服中心)· Codex 规格 v1

> 目标:独立站联系表单直连控制台。站上两个表单(零售 contact 页 / 批发 wholesale 页)→ WP 瘦插件服务端转发 → 控制台公开入站端点 → 落库 → CS 收件箱(**B 端与 C 端物理分队,绝不混排**)。
> 分工:**Codex = 控制台后端模块 + 控制台前端 CS 界面**;Claude = WP 瘦插件、站点页面改造、部署与端到端验证。无远程仓库不 push。

## 0. 归属与命名
- 模块归 **国际贸易组织**(与 K/P/F 同一 org 体系),模块 key:`cs.customer_service`,权限前缀 `cs.*`(比照既有系列:owner 全量;权限键至少 `cs.customer_service.read` / `.update`)。
- 侧边栏:**新系列必须加进组织树的硬编码前缀白名单**,否则整个系列隐身(W-A 踩过的坑)!加 `cs` 前缀;**F 系列的条目一个字符都不许碰**(死命令)。

## 1. 数据模型 + 迁移
表 `cs_messages`:
- id UUID pk;org 作用域字段与既有系列一致(workspace_key 等)
- `channel` enum:**`retail` | `wholesale`**(B/C 分队的根)
- `name`(<=120)、`email`(<=254)、`company`(<=200,B端用,可空)、`order_number`(<=64,C端用,可空)
- `message` text(<=5000)
- `source_url`(<=500)、`client_ip`(<=64)、`user_agent`(<=300)
- `status` enum:`new` | `in_progress` | `resolved` | `spam`,默认 new
- `internal_note` text 可空(客服内部备注)
- created_at / updated_at
索引:`(channel, status, created_at)`。
**迁移铁律**:先 `ls backend/alembic/versions/` 找 head 单链分叉;迁移不自动跑(Claude 手动执行后才发版)。

## 2. 公开入站端点(站点 → 控制台)
`POST /api/public/cs/inbound`(无登录;这是全站第一个公开写入口,安全从严):
- **鉴权**:请求头 `X-BY-CS-KEY` 必须等于环境变量 `CS_INBOUND_KEY`(常量时间比较;缺失/不符→401,响应体不带原因细节)。Claude 负责在生产 compose env 注入该变量。
- **限流**:每 IP 每分钟 ≤5、每小时 ≤20(内存/DB 简易实现即可);超限 429。
- **校验**:channel 只收 retail/wholesale;email 格式;message 非空且 ≤5000;字段长度全部服务端截断/拒绝;剥 HTML(存纯文本)。
- **反滥用字段**(由 WP 插件转发):`honeypot`(非空→静默丢弃但返回 200,别教蜘蛛)、`form_ms`(表单填写耗时,<3000ms→按可疑标记 status=spam 落库而非丢弃)。
- 成功:落库 + 调用**既有通知服务**(P 系列在用的 create_notification)发一条站内通知:标题区分「新零售咨询」/「新批发询盘」,进右上角铃铛。
- fail-safe:通知失败不影响落库与 200 返回。

## 3. 管理端 API(控制台登录态)
- `GET /api/app/cs/messages?channel=retail|wholesale&status=&page=` —— **channel 必填**(接口层面就不给"混排"留口子),按 created_at 倒序,分页。
- `GET /api/app/cs/messages/{id}`
- `PATCH /api/app/cs/messages/{id}`:status 流转 + internal_note。
- `GET /api/app/cs/summary`:两队各自的 new 数(给侧边栏/收件箱角标)。
- 权限:read 用 `cs.customer_service.read`,PATCH 用 `.update`。

## 4. 控制台前端(CS 模块界面)
- 路由 `/cs/customer-service`,侧边栏挂国际贸易组织下,名称「客服中心」。
- **顶层两个分队 Tab:「C端 · 零售咨询」/「B端 · 批发询盘」**——两个独立列表、独立角标(new 计数),**无"全部"混排视图**(产品要求)。
- 列表列:状态徽章(new=琥珀/in_progress=蓝/resolved=灰/spam=红)、姓名、email、(B端多一列公司)、消息摘要 40 字、时间。行点开抽屉/详情:全文、来源 URL、订单号/公司、UA/IP,`mailto:` 快捷回信按钮(带 Re: 主题),状态下拉 + 内部备注保存。
- 新消息进既有通知铃铛(后端已发,前端确保通知点击可跳转到对应分队)。
- 风格走现有 command-center 家规(globals.css 追加层,复用现有徽章/表格样式)。
- **新增 API 路径全部登记前端代理白名单**(tests/frontend/proxy-allowlist-drift 会抓;public 入站端点不走前端代理,无需登记)。

## 5. 测试
- 后端:入站鉴权(无 key/错 key 401)、限流 429、honeypot 静默丢、form_ms 快速提交标 spam、channel 校验、列表 channel 必填、状态流转、summary 计数。`bash scripts/run_backend_tests.sh unit` 全绿。
- 前端:`npm test -- --run` 全绿(代理白名单契约含新路由)。

## 与 Claude 的接口契约(冻结,双方按此对接)
- 入站 payload(JSON):`{"channel":"retail|wholesale","name":"","email":"","company":"","order_number":"","message":"","source_url":"","honeypot":"","form_ms":12345}`(client_ip/user_agent 由服务端从请求提取,WP 转发时用头 `X-Forwarded-For-Origin` 传真实访客 IP,服务端优先取它)。
- 成功响应:`{"ok":true}`;失败 4xx `{"ok":false}`(不带细节)。
- 环境变量名:`CS_INBOUND_KEY`(Claude 注入生产值并在部署时提供)。

## 硬约束
- 侧边栏白名单加 `cs`,**F 不碰**;fail-safe/权限模式照抄既有系列;别造假。
- 完成后 Claude 做端到端:站上两表单各投一发 → 控制台两分队各见其一、互不串门、铃铛响。

## 交付
本地提交 + 双端测试绿 + 每任务一句根因/做法说明。
