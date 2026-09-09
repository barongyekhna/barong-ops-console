# 数字员工 03 · 殷承岳(贸易公司产品助理)· v1

> 给人看的。在 C19 通讯里问他「这个产品是哪个类目」,他告诉你谷歌类目树里那个具体类目的英文名和理由,英文名一键复制。

## 1. 他是谁
| | |
|---|---|
| 名字 | 殷承岳 |
| 岗位 | 产品助理(贸易公司) |
| 系统 ID | `product.yinchengyue`,登录名 `yinchengyue`,标记为机器人 |
| 管什么 | 只判类目:产品 → 谷歌商品分类树(`k_category_google`,5595 个类目,带中文名)里的一个类目 |
| 脑子 | `deepseek-v4-flash`,每次判定跑两次,每次 25 秒超时 |
| 在哪找他 | C19 通讯里搜「殷承岳」,直接私聊;谁都能问 |

## 2. 他怎么干活(四步)
1. **翻成英文词**(模型):你的中文 / 英文 / 1688 标题 → 3 到 6 个英文检索词 + 一句英文描述。模型只做翻译。
2. **查候选**(代码):用英文词查类目的英文名和完整路径,用原话里的中文片段查中文名;合并、去重、叶子优先,最多 25 个**真实存在**的类目。
3. **在候选里选**(模型):只准从这 25 行里挑一个 id,附置信、中文理由、最多两个备选。
4. **校验并回卡**(代码):模型给的 id 不在候选里 → 当作没选,回「说清楚一点」;在 → 取完整路径,回一张类目卡。

## 3. 回复长什么样
```
【类目 #a1b2】Camping Cookware
路径:Sporting Goods > Outdoor Recreation > Camping & Hiking > Camping Cookware
中文:露营炊具
原因:描述是户外炉具加锅具套装,属于露营烹饪器具而非家用厨具。
备选:Portable Cooking Stoves — 若产品主体是炉头
置信:高
⟦category:a1b2⟧
```
控制台前端认出首末两行的标记,渲染成卡片:英文名大字 + 复制按钮,每个备选也带复制按钮。别的客户端看到的仍是这段可读文本,英文名就在首行。

## 4. 三个灯
| | 情况 | 处理 |
|---|---|---|
| 🟢 | 问产品类目 | 直接答 |
| 🟢 | 打招呼 / 问他是谁 | 固定一句自我介绍,不调模型 |
| 🔴 | 改类目、建产品、任何写入 | 他没有这些动作,连接口都没接 |

## 5. 硬规矩(都在代码里,不在提示词里)
- 候选由代码查表得出,模型选了候选外的 id 一律作废(`classifier.validate_choice`)。
- 拿不准就说拿不准:候选为空、模型答 NONE、模型给的词是空 → 都回「再说清楚一点」,不猜。
- 同一条 C19 消息只答一次(`state/answered.json`);一个会话里连发多条只答最新一条。
- 每次模型调用记台账(桶 `agent_chat_yinchengyue_deepseek`,预算 0 = 只记数)。
- 每次回答进 `operation_log`(`agent.category.answer` / `agent.category.none`),details 里有选中的类目 id、候选数、置信。
- 一轮轮询干完写 `worker_heartbeats(yinchengyue-worker)`;失联由 `scripts/check_worker_heartbeats.py` 和主页站点健康卡报。

## 6. 部署
- 身份:owner 在控制台「用户管理 → 注册机器人」建号:登录名 `yinchengyue`、显示名 `殷承岳`、岗位 `产品助理`、组织=涌龙麟(深圳)国际贸易有限公司、简介见 `constants.AGENT_BIO`、密码 ≥12 位。密码写进 `.env.production` 的 `YINCHENGYUE_PASSWORD`。
- 容器 `yinchengyue-worker`(`docker-compose.production.yml`),镜像同 backend;`scripts/rebuild_workers.sh` 里已列入。
- 登记:`docker exec yinchengyue-worker python -m backend.app.modules.agent_series.yinchengyue.bootstrap`(只收敛 `agent_registry`;加 `--with-user` 可幂等修补已存在账号的岗位 / 简介 / 成员关系,不代建号)。
- 状态:`console_agent_memory_data` 卷下 `yinchengyue/state/answered.json`。
- 前端的类目卡渲染在 `frontend/src/modules/c19/C19CategoryCard.tsx`,要随前端一起发版。

## 7. 欠账
- DeepSeek key 借 K 系列的绑定(org=深圳,module=`k.product_knowledge`),同白苏婉、霓旌。
- 主循环是第三份复制,下一位员工之前抽 `common/worker_base.py`。
- 一期不做:主页卡、内联把类目一键绑到 K 产品上、群聊 @ 识别、判定中途的「在查」提示。
