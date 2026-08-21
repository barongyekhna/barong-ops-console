# 数字员工 02 · 霓旌(制造公司库管员)· v1

> 给人看的。她在 C19 通讯里听你说一句「今天入库一千条桌腿」,替你去 M 系列库存开单。

## 1. 她是谁
| | |
|---|---|
| 名字 | 霓旌 |
| 岗位 | 库管员(制造公司) |
| 系统 ID | `mfg.nijing`,登录名 `nijing`,标记为机器人 |
| 管什么 | 入库 / 生产 / 发货 / 盘点调整 / 查库存 / 查单据 / 撤销 |
| 脑子 | `deepseek-v4-flash`,只负责「听懂」,30 秒超时 |
| 在哪找她 | C19 通讯里搜「霓旌」,直接私聊 |

## 2. 她怎么干活(一句话的五步)
1. **听懂**(模型):把你的话翻成 `{intent, item, qty, unit, note, reason}` 这一个 JSON。模型只做这一步。
2. **对账本**(代码):「桌腿」→ 物料表里找 `TBL-LEG`。对不上就问回去:多个像的让你选;没有就说没有;单位不符就问。**绝不猜。**
3. **预演**(代码):生产用 M 的预演接口,算出每样物料扣多少、够不够。
4. **确认卡**:每一笔写入都先回一张卡,你回「确认」才执行,「取消」作废;30 分钟不理自动作废;别的消息进来旧卡也作废。
5. **落单**(代码,进程内直接调 M 的 service):单据上的操作人是**你**,备注里带你的原话和那条消息的 ID。回你单号和最新库存。

## 3. 三个灯
| | 动作 | 处理 |
|---|---|---|
| 🟢 | 查库存、查单据 | 直接答 |
| 🟡 | 入库、生产、发货、盘点调整、撤销 | 必出确认卡 |
| 🔴 | 新建物料/成品、改配件清单、归档 | 她告诉你去控制台,自己不碰 |

## 4. 按谁说话算谁的权限(这次是真做了)
白苏婉那版"按说话人权限"只是文档意图。霓旌是**进程内以说话人的 `User` 行**调 M 的 service,执行前过的是和网页同一个门 `service.user_may_access`:只有 owner 和制造公司自己的 super_admin。她自己的账号是 viewer,**没有任何权限码**;别人跟她说话,得到的是"帮不了你"。

## 5. 必须知道的几条硬规矩(都在代码里,不在提示词里)
- 数量不信模型:模型说的数字必须能在你的原话里找到(中文数字已归一),找不到就让你重说。
- 一句话多件事 → 拒绝,让你分开说。
- 同一条 C19 消息永远只执行一次;一张卡只有开卡的人能确认。
- 脑子超时/出错 → 「没接通,什么都没做」,不会带着不确定往下走。
- 撤销 = 反向盘点调整(系统本就没有删单),原因自动写「冲销 XX」;冲销单不能再被冲。
- 每次执行/拒绝都进 `operation_log`,`actor_type=agent`。

## 6. 部署
- 容器 `nijing-worker`(`docker-compose.production.yml`),镜像同 backend;`.env.production` 里 `NIJING_PASSWORD`
- 建号:`docker exec -e PYTHONPATH=/app/backend console_backend python -m backend.app.modules.agent_series.nijing.bootstrap`(幂等;挂 `org_type=factory` 的组织)
- 记忆/状态:`console_agent_memory_data` 卷下 `nijing/`(`state/pending.json` 待确认卡、`state/executed.json` 已执行消息、`conversations/<user>.md`)
- 台账桶 `agent_chat_nijing_deepseek`(`NIJING_CHAT_DAILY_BUDGET`,0=只记数)

## 7. 欠账
- DeepSeek key 借 K 系列的 (org=深圳, module=k.product_knowledge) 绑定,同白苏婉;key 管理里给 `mfg.inventory` 单独绑一把后改 `brain.py`
- 白苏婉尚未迁到 `agent_series/common/`
- 一期不做:主动开口(安全库存线)、多件事拆卡、群聊 @ 识别
