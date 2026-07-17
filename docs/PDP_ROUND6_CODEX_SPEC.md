# PDP 第六轮 · Codex 规格(第五轮实战补刀,小而准)

> 背景:第五轮 CCD-005(Woo #3854)端到端通过,round-5 四大目标全部验证(卖点 8/10 原样直过、英制声明直过、FAQ 可见=schema 3 条一致、标题健康)。过程暴露 2 个残余缺陷,均已实锤定位与手工绕行。**五个对比产品(#3803/#3812/#3821/#3837/#3854)都不许动**;验证走新产品(CCD-006)。无远程仓库不 push。SKILL.md 归 Claude,勿改。

## 1. 【主刀】卖点 id 空洞 → 图片 brief 绑定死锁
**实锤**:10 条候选拒掉 2 条后,已审集 id 变成 `bp1,bp3,bp4,...bp9`(有空洞)。`_bind_image_to_selling_point` 要求 **id 命中与 1-based 序号命中必须指向同一条**;AI 按 "bp5=第5条" 的自然假设填,实际 bp5 在已审列表第 4 位 → 永远对不齐 → `generate_image_brief` **确定性死循环失败**(连挂 3 次)。手工绕行=重新 approve 一遍把 id 重排连号(bp1..bpN)后立即通过。
**修(两处都做,双保险)**:
- **批准端(治本)**:`selling-points/approve` 落库前把保留 bullets 的 `id` **自动重排为连号 bp1..bpN**(与列表顺序一致);`selling_point_index` 相关下游一并以新序为准。evidence_digest 只哈希 evidence_snapshot,改 id 无副作用(已实测)。
- **绑定器(容错)**:`_bind_image_to_selling_point` 当 **id 精确命中**时直接采用该条,不再要求 index/text 同时对齐(index/text 仅在无 id 时作为回退匹配途径;三者冲突时以 id 为准并记 debug 日志)。
- 回归测试:①带空洞 id 的旧数据(bp1,bp3)approve 后被重排连号;②AI 给 id=bp3+index=3(错位)时 binder 按 id 成功绑定;③无 id 只有 index 时仍可绑定。

## 2. dispatch API 路由残余 409(顺手项,这次务必做掉)
**实锤(连续三轮复现)**:`POST /api/app/p/products/{id}/dispatch` 在 `gate_blockers` 为空、workflow 已 exported 的状态下仍返回 409(生产环境错误脱敏后只见 "Request conflict.");同一时刻**容器内直调** `create_dispatch_job(db, product_id=..., channel="woocommerce", public_base=...)` 成功派单且 n8n 正常执行。说明 409 出在 **route 层 gate 之外的某个附加校验/异常映射**(可能:`_load_product` 的 scope/加载分支、路由级 execution 状态复核、或某处 IntegrityError→409 的异常映射)。
**修**:定位 `p_dispatch` 路由从进入到 `create_dispatch_job` 之间所有可能抛 409 的路径,找出与容器内直调的行为差(建议本地写一个直接调 route 函数的测试复现),修掉或让错误信息带真实原因(内部日志必须打出原始异常,别再被脱敏吞掉)。回归:门禁全清的产品经 API dispatch 成功。

## 3. 小噪点(便利就修,不强求)
- 描述"What's in the box"出现两次(copy 的 H2 小节 + 模板自动 bullet 清单)——保留一处即可(建议保留 copy 小节,模板 bullet 段在 copy 已含该小节时跳过)。
- `render-assets/save` 在暂存为空时返回 409:改为幂等 200(空操作),减少编排侧误报。

## 硬约束
- 五个对比产品不动;fail-safe/品牌硬门/别造假不变;测试 `bash scripts/run_backend_tests.sh unit` 全绿。
- 完成后 Claude 用 CCD-006 端到端验证(重点:拒点后 brief 一次过、API dispatch 直接通)。

## 交付
本地提交 + 测试绿 + 每条一句根因/修法。

## 4. 【补充,与 #1 同优先】描述区图片被图廊配额挤没(round-4 回归)
**实锤**:CCD-005 图组总数 7:gallery 铁律吃 6 张,**description 只剩 1 张**→ 图文交替模块退化成 1 个+大段秃文字(对比 round-3 CCD-003 描述有 3 张)。SKILL.md 已由 Claude 补"description ≥3 张 4:3 proof_scene、总数 9-10"的硬规则。
**修(代码校验)**:`_normalize_evidence_driven_image_brief` 增加断言:`placement=description` 的图 **≥3 张**(与 gallery 配额并列检查,同样的打回重出机制);相应调 `_IMAGE_BRIEF_*` 常量与错误文案。回归:6+1 的图组被打回,6+3 通过。
