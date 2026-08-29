# K 系列外部精修通道(MCP)—— 让 Codex 桌面版给 K 作图

## 为什么有这条通道

K 的 worker 管线走 gpt-image API 一次性出图,长期栽在两处:产品几何变形、物理机制画错(潜水泵搁岸上)。
2026-08-26 用 PSPE-001 的简报+三色参考图在 Codex 桌面版(内置 gpt-image-2,最多吃 16 张参考图,自带看图迭代)实测:
三色主图几何全对、灰色款连黑管+刷毛花洒头都按对应参考图来、三张场景图泵全部入水——API 管线反复犯的错一张没犯。

**定位:不替代 worker 管线,是给 K 加一条「有眼睛的精修通道」。** 批量粗跑仍走 k-worker;难搞的主图/场景图由你在 Codex 里驱动出图。

## 三条硬边界

1. 交回来的图走 worker 自己的入库函数(`_store_render_asset`):WebP 强转、信息层、派生图、完整 metadata、品牌/几何/物理审查一个不少。
2. **只落 `staged`;人在控制台点「保存」才 `available`。** 机器人只能交稿,不能发布。
3. 执行者是拿钥匙的那个**真人**(见下「身份与钥匙」);他挂哪些组织,K 的作用域就是哪些组织;能不能看/交按他的 K 权限算。

## 架构

```
Codex 桌面版 ──(Streamable HTTP MCP + Bearer)──▶ nginx  location ^~ /mcp/k-images
                                                  └──▶ 容器 k-mcp (127.0.0.1:8095)
                                                        进程内 import backend.app,直连 DB
```

- 协议层:`backend/app/mcp/k_images_server.py`(官方 `mcp==1.29.1`,无状态,`json_response=True`)
- 业务层:`backend/app/modules/k_series/product_knowledge/mcp_channel.py`
- 镜像:`backend/Dockerfile.k-mcp`(主后端镜像零变化;`sse-starlette` 钉 3.0.2 否则会拽炸 starlette 0.46.2)
- MCP 面不走 Next 代理白名单、不改 K 权限码;钥匙管理走控制台自己的 `/profile/me/mcp*` 与 `/users/{id}/mcp-token-*` 端点(表 `mcp_access_tokens`,迁移 `20260828_01`)。

## 五个工具

| 工具 | 参数 | 干什么 |
|---|---|---|
| `k_list_products_awaiting_images` | `limit` | 有简报的产品,哪些位号还没有已保存的图 |
| `k_get_image_brief` | `sku` | Markdown 简报:产品机制、只准画的配件、每个位号的**最终提示词**(和 worker 逐字同源)、比例、状态、参考图下载链接(1 小时有效) |
| `k_get_reference_images` | `sku` | 参考图字节(MCP image 块)+ 下载链接 |
| `k_submit_image` | `sku, position, image_base64, note?` | 交一张图 → staged → 立刻排审查 |
| `k_get_submission_status` | `sku` | 各位号状态 + 审查发现(brand/geometry/physics),据此改了重交 |

## 身份与钥匙(2026-08-28 起:每人一把)

- 每个**真人账号**一把 MCP 个人钥匙(`bk_…`),表 `mcp_access_tokens` 只存哈希;明文只在生成/重置那一刻显示一次。机器人账号不发。
- 钥匙只证明「你是谁」;能不能看 K 简报 / 交稿按那个人现有的 K 权限算(看=`k.product_knowledge.read` 或 `products.read`;交稿=`k.product_knowledge.update`;owner/super_admin 直通)。没权限 → 工具返回 `PERMISSION_DENIED`。
- 交上去的图记在那个人名下(`created_by_user_id` + `metadata.submitted_by_username`),控制台卡片显示「某某 · Codex 精修」。
- **owner / super_admin** 在「用户管理」里可对每个人:重置(新钥匙明文只显示一次,由管理者转交)/ 停用(即刻生效,他的 Codex 立刻 401)/ 启用。super_admin 只能管本组织的人。
- **总览在侧边栏「接入钥匙」模块**(仅 owner / 超管可见):全员列表(头像/姓名/职位/组织/钥匙状态/上次使用)+ 按组织与状态筛选 + 操作记录;行内可重置/停用/启用。
- 本人在「设置 → 头像与昵称」页有「Codex / MCP 接入钥匙」区块:生成 / 重置,当场显示 Mac / Windows 装机命令。被管理员停用的钥匙本人不能靠重置复活。
- 发钥匙 / 重置 / 停用 / 启用都写 `operation_logs`(`mcp_token.issue|reset|disable|enable`);钥匙表记 `last_used_at / last_used_ip`。
- 同一把钥匙走**所有**未来的 MCP 服务(鉴权层 `backend/app/mcp/auth.py` 模块无关);新模块只声明自己的权限要求。
- 旧的全局钥匙 `K_MCP_BEARER_TOKEN` / 固定执行者 `K_MCP_ACTOR_USERNAME` 已退役;sidecar 只要 `K_MCP_FILE_SIGNING_KEY`(参考图签名链接,链接里签了用户 id)。

## 接入步骤

### 1. 服务器侧(一次)

1. `.env.production` 必须有 `K_MCP_FILE_SIGNING_KEY=<openssl rand -hex 32>`(`K_MCP_BEARER_TOKEN`/`K_MCP_ACTOR_USERNAME` 可删)。
2. nginx:`deploy/nginx/ops.barongyekhna.com.conf.template` 里 `location ^~ /mcp/k-images` 块(已上线)。
3. 起容器:`docker-compose -f docker-compose.production.yml up -d --build k-mcp`,日志出现 `k-mcp ready (per-user tokens)`。
4. 验:`curl -s https://ops.barongyekhna.com/mcp/k-images/health` → `{"ok":true}`;不带钥匙 POST → 401。

### 2. 每个人自己(每台电脑一次)

1. 登录控制台 → 右上角「设置」→ 头像与昵称 → 「Codex / MCP 接入钥匙」→ 生成钥匙。
2. 复制对应系统那一行命令,贴进电脑终端回车(它会存钥匙、写 Codex 配置、当场验证)。
3. 彻底退出 Codex 再打开,新建对话输入 `/mcp`,看到 `barong_k_images` 下的工具。

在 K 产品页作图指令板块也有同一个入口(「新电脑接入 Codex」),以及「唤起 Codex 作图」(打开本机 Codex 并预填指令)。

### 3. 工作流(在 Codex 里说人话就行)

> 「用 barong_k_images 列一下等图的产品」→「取 PSPE-001 的简报和参考图」→「按简报出第 1 张,用全部参考图」→「交上去」→「看看审查结果」→「按发现改了重交」

或直接在控制台点「唤起 Codex 作图」,指令已经填好。你在控制台 K → 产品 → 作图面板会看到带「✦ Codex 精修」徽章、记着你名字的暂存卡;审查结果在品牌审查面板;点保存才生效。

## 边界与已知摩擦

- 只能交简报里存在的位号;配件只准画 `package_includes` 里列的(简报里写明)。
- 外部稿**不吃** 24h 暂存回收,也**不会**被 worker 自动重渲盖掉——你自己看报告改。
- 参考图链接 1 小时过期(且绑定取链接的那个人),过期就重新取简报。
- 2K 图 base64 约 10MB,nginx 该 location 已放宽到 32m;单张超过 25MB 服务端直接拒(多半是交了拼版)。
- Codex 桌面版能否把 MCP 返回的 image 块直接当作图参考尚不确定——简报里同时给了下载链接,让它 `curl` 到本地再喂给自家 image_gen。
