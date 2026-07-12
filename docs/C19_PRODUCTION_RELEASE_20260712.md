# C19 Production Release

日期：2026-07-12 UTC

状态：C19 已正式部署到 production。数据库迁移、三域服务、Nginx 公网边界、
真实 HTTPS 全链路验收、验收账号停用与会话失效复核、临时朋友圈清理、上线后
一致性备份和恢复准入验证均已完成。

## 1. 生产产品合同

C19 是每个已认证且有效的 Barong 用户都拥有的基础通信能力。进入 C19、使用全局
通讯录、好友、直聊、群聊、消息、聊天资产和朋友圈，不以 RBAC 权限、角色、组织、
组织成员身份或 affiliation 作为准入条件。

每个用户只有一份全局通讯名片，可以拥有零个、一个或多个组织 affiliation。
affiliation 只用于名片描述、通讯录筛选，以及用户显式选择 `org` 朋友圈受众时的
组织信息；缺少 affiliation 不会阻止 C19 基础功能，也不会由服务端猜测或制造组织。

通用功能不等于通用内容访问。会话成员身份、群 owner/admin/member 规则、屏蔽关系、
朋友圈发布受众与当前可见关系、资产所有权和短期 ticket、账号状态与会话状态仍是
内容隐私和完整性边界。

## 2. 发布身份

| 项目 | 生产身份 |
| --- | --- |
| C19 Stage 1–6 主实现 | `89eda1c` |
| PostgreSQL 17 catalog 兼容修复 | `610c42e` |
| PostgreSQL 约束名兼容修复 | `f004f54` |
| ClamAV watchdog socket 修复 | `c6a4955` |
| 应用镜像版本 | `f004f54` |
| 生产部署源 HEAD | `c6a49556a175928e18585998bdcc1ba2ed25b26e` |
| 生产部署源 HEAD tree | `d4b8b1843af7cec7b8fdd383bbcc5a32801581bc` |

应用 backend/frontend/worker 镜像基于 `f004f54`；`c6a4955` 只改变 ClamAV 部署
配置，不改变应用代码。

生产镜像身份：

- backend 和四个 worker：
  `sha256:861720277eb2cd7a2b51692a4ef42180e45b433b7f67cc2903016898943eba25`；
- frontend：
  `sha256:2c3a64c7ead238e6d1523146855fa8307a8f01851ebacea51994c8f182039f22`；
- Record Service：
  `sha256:f0c58c4efa97d87cdddc82e8431d48e6e29ad9d95fff060d472aa5c278a0d096`；
- Asset API/Gateway/Worker：
  `sha256:826e5294b6d0b50920ce9d0fbf838c4db97b956b6644025231f3b5480fe4bd9e`；
- ClamAV：
  `sha256:b70a05497f80d768e659ae4255bc32def08848deec8d5421e052ef8f8410472f`。

## 3. 数据库迁移与身份模型

实时生产 revision：

- Barong：`20260712_01_c19_native_access`；
- Record：`c19_record_20260712_04`；
- Asset：`c19_asset_20260712_03`。

主库验收结果：

- 有效用户缺失 `c19_profiles`：`0`；
- `c19_conversation_members.affiliation_id`：nullable；
- `c19_conversation_members.org_id_at_join`：nullable；
- affiliation snapshot 一致性约束：validated；
- conversation member 到全局 profile 的外键：validated。

这证明零 affiliation 用户是生产 schema 的正式状态，而不是特殊兼容分支。

## 4. 生产拓扑与网络边界

生产 Compose projects：

- 主系统：`barong-ops-console`；
- Record：`c19-record`；
- Asset：`c19-asset`。

最终端口边界：

- frontend 仅绑定 `127.0.0.1:3000`；
- backend 仅绑定 `127.0.0.1:8000`；
- Asset gateway 仅绑定 `127.0.0.1:8092`；
- 三个 PostgreSQL、Record Service、Asset API 和 ClamAV 均无宿主机端口发布；
- 公网流量只通过 `https://ops.barongyekhna.com` 的 Nginx 边界进入。

Record 和 Asset 当前部署在本 VPS。其数据集身份、HTTP 接口、对象卷、备份格式和
恢复准入保持可迁移；本次发布没有连接另一台 VPS，也没有把运行时绑定到不可迁移的
宿主机路径协议。

## 5. Nginx 与公网边界验收

生产 vhost 已合入并激活 10 个 C19 精确 location，覆盖 Chat SSE、Moment SSE、
消息体上限、Asset 内部授权、精确上传/下载 ticket，以及 malformed/legacy 路径拒绝。

最终结果：

- `nginx -t`：syntax ok、test successful；
- Nginx：`active`；
- graceful reload：完成；
- `/health`、`/login`、`/c19`：`200`；
- 未登录 `/api/backend/c19/directory`：`401`；
- 44 字符畸形 ticket：`404`；
- legacy `/api/c19-assets/...`：`404`；
- 形状有效但无会话的上传 ticket：`401`；
- `scripts/production_smoke_check.sh`：通过。

Nginx 的 pre-C19 配置快照保存在：

- `backups/config/ops.barongyekhna.com.pre-c19-20260712T150910Z`；
- `backups/config/ops.barongyekhna.com.pre-c19-f004f54`。

两个快照均为 `0600`。`nginx -t` 仍显示 C01 已记录的其他 vhost warning；它们不属于
C19 vhost，且不影响本次语法检查、加载或生产验收。

## 6. 真实生产全链路验收

生产 HTTPS E2E 总结果：`pass`，耗时 `46.403s`。

覆盖范围：

- 无 affiliation 用户的 C19 通用访问、全局目录、好友及相互通信；
- 直聊、群聊、群创建与成员访问、消息写入及 Chat SSE；
- 文件和图片的 intent、上传、扫描、finalize、消息绑定和读取；
- 下载、`HEAD`、`Range` 和 Range `HEAD`；
- 朋友圈发布、friends 可见性、非好友隔离与 Moment SSE；
- 点赞、评论、幂等重试和删除；
- 账号禁用、匿名访问和内容边界拒绝。

验收清理结果：

- 遗留验收朋友圈第一次清理：`pass`，`cleaned=1`；
- 幂等复核：`pass`，`cleaned=0`；
- `c19acc_` 验收账号：总数 `27`，active `0`，inactive `27`；
- 验收账号标记异常：`0`；
- 验收账号未失效且未过期会话：`0`；
- Moment：draft `0`、published `0`、delete_pending `0`、合法 deleted 墓碑 `3`；
- 验收 Moment published：`0`；
- active like/comment 和非活动 Moment 资产引用：均为 `0`。

直聊、聊天记录和验收聊天资产没有使用未批准的人工删除；它们保留在正式数据生命周期
中，后续只由既定 retention 策略处理。

## 7. 最终运行态

最终容器验收：

- 主 frontend/backend、四个 worker、Record Service、Asset API/Gateway/Worker、
  ClamAV 及三个 PostgreSQL 全部 running；
- 定义了 healthcheck 的服务全部 healthy；
- 所有生产容器 `restart=0`、`OOM=false`；
- Asset `volume-init` 按设计为一次性任务，状态 `exited (0)`；
- ClamAV 同时保留私有 TCP 扫描接口和 watchdog 所需 Unix socket，worker `PING`
  验证通过。

Record 聚合：

- asset deletion pending/authorized/blocked/leased：均为 `0`；
- draft、delete_pending 及其 oldest age：均为 `0/null`；
- Record ops snapshot：`status=ok`。

Asset 聚合：

- pending_upload/uploaded/scanning/delete_pending：均为 `0`；
- retention prepared：`0`；
- active transfer tickets：`0`；
- active：`11`，quarantined：`2`；quarantined 为验收期间被正确隔离的无效制品，
  不属于处理 backlog；
- Asset ops snapshot：`status=ok`，dataset 为 `barong-c19-assets-production`。

最终备份完成并恢复 writers 后统计的 14 个生产服务关键错误模式计数均为 `0`。

宿主资源：

- 内存总量约 `7.9 GiB`，available 约 `3.4 GiB`；
- swap 总量约 `2.4 GiB`，可用约 `1.8 GiB`；
- `/dev/vda2` 总量 `150 GiB`，可用 `83 GiB`，使用率 `43%`。

## 8. 生产备份与恢复准入

上线前主库备份：

- `backups/postgres/barong_ops_20260712T150910Z.dump`；
- SHA-256：
  `1fdcf8e55545d06ecb9e004ce090bc1b19e63a1248ddae5d03f06118312a28ba`；
- PostgreSQL custom archive catalog 验证：通过。

上线前协调三域基线：

- generation：`c19-prod-preactivate-final-20260712T155000Z`；
- manifest SHA-256：
  `f22bb6afea969a476ad25d9b391316d859e8b32e2137bb0478096bad56a02e35`；
- 结果：completed and verified，source writers running。

上线后最终协调三域备份：

- generation：`c19-prod-postlive-20260712T172012Z`；
- manifest：
  `backups/c19-full/c19-prod-postlive-20260712T172012Z/c19-full-c19-prod-postlive-20260712T172012Z.json`；
- manifest SHA-256：
  `2196c81ba73be75e5f790e325869945d311f570aa51e8510da2fe9e5ac12957c`；
- capture quiesce：`20260712T172108Z` 至 `20260712T172658Z`；
- sealed：`20260712T172700Z`；
- 结果：`C19 full backup completed and verified`；
- 捕获期间：所有 C19 writers stopped；
- 完成后：`source_writers_running: yes`；
- 三个 revision 和三个 production dataset 精确匹配；
- 8/8 制品尺寸与 SHA-256 匹配；
- 3/3 数据库归档具有 PostgreSQL custom archive magic；
- Asset 对象：`14` 个，共 `202773` bytes；
- required tables：seal 前已验证；
- generation 及子目录：`0700 root:root`；
- manifest、签名、归档与元数据：`0600 root:root`；
- HMAC 与独立 restore-admission 验证：通过；
- 最终 generation 大小约 `81 MiB`。

`c19-prod-postlive-20260712T171311Z` 在一次长任务会话跟踪中断后受到外部恢复干预，
因此未满足全 writers 同时停止的断言。协调器正确拒绝封签，未产生 accepted manifest；
该 partial generation 保持隔离，不能作为恢复点。随后所有 writers 均恢复，最终 generation
在可跟踪的单一会话中重新完成并通过全部准入门禁。

## 9. 回滚材料

本地 pre-C19 镜像标签已保留：

- `barong-ops-console_console_frontend:pre-c19-20260712`；
- `barong-ops-console_console_backend:pre-c19-20260712`；
- `barong-ops-console_r-w-worker:pre-c19-20260712`；
- `barong-ops-console_r-a-worker:pre-c19-20260712`；
- `barong-ops-console_k-worker:pre-c19-20260712`；
- `barong-ops-console_key-health-worker:pre-c19-20260712`。

回滚材料还包括主库上线前 dump、preactivation 三域 bundle、post-live 三域 bundle 和
两个 Nginx pre-C19 配置快照。自动全系统 restore 被刻意禁止；恢复前必须先通过 HMAC、
哈希、dataset、revision、archive 与对象清单准入，再按隔离目标中的 Barong、Record、
Asset 顺序执行组件 runbook。

## 10. Git 边界与结论

C19 主实现和三项生产热修复均已提交。本次生产发布使用 clean release archive，未包含
当前工作区中的 F 系列开发内容。该 F 系列内容未被暂存、未进入 C19 镜像，也未进入
C19 发布提交。

C19 production 的正式迁移、服务激活、公网路由、所有用户通用访问、聊天、聊天资产、
朋友圈、实时事件、内容安全边界、上线后一致性备份和恢复准入均已验收通过。
