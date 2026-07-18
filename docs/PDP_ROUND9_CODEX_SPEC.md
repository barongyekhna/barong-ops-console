# K 第九轮 · Codex 规格(类目规格模板 + 1688 粘贴解析 + 必填校验)

> 背景:1688 寻源通权限门槛为月采购额 12 万,当前不可达 → 规格进入方式转为**运营手动录入**。现有 K 手动规格区是"裸表单"——系统不知道该类目要填哪些字段(炊具不该出现电池栏,灯具必须逼填流明/IP)。本轮把手动录入升级为**类目驱动 + 粘贴解析**,让运营流程变成:开 1688 → 复制规格表 → 粘贴 → 扫一眼 → 保存。
>
> 数据契约不变:一切落 `structured_specs_json` v1.0(标准键 + additional_specs + package_includes),下游(规格表/Woo属性/schema/叠字/证据门)零改动。七个测试品(#3803…#3864)不动。无远程仓库不 push。SKILL.md 归 Claude。
> **注意**:Claude 正在并行改「K 手动创建禁填 SKU、按叶子类目自动发号」(前端 ProductForm + create 端点),避开这两处;类目选择器可复用其成果。

## 1. 类目规格模板(核心)
**模型**:新表(或 K 类目树表加 JSON 列)`k_category_spec_templates`,按**叶子类目**挂一份模板:
```json
{
  "category_id": "<K 叶子类目>",
  "status": "draft | approved",
  "fields": [
    { "key": "capacity_pot",            // 落 additional_specs 的稳定 key;或标准键名(如 battery_capacity_mah)
      "target": "additional|standard",  // 落哪层
      "label_zh": "主锅容量",            // 运营看的
      "label_en": "Main pot capacity",  // 买家看的
      "value_type": "number|text|enum|boolean",
      "unit": "L",                      // 输入单位(公制);展示层照旧自动转美制
      "required": true,
      "enum_options": null,
      "hint_zh": "锅体最大容积"
    }
  ]
}
```
- **生成**:某叶子类目第一次需要模板时,AI 起草(prompt:"该类目买家最关心的 8-12 个规格字段,含中英文标签/类型/单位/必选"),落 `status=draft`;**运营在前端审定**(增删改字段)→ `approved`。之后该类目所有产品共用,可随时再编辑。
- **约束**:字段 key 与标准键冲突时必须 `target=standard`(电池容量只能是 `battery_capacity_mah`,禁止在 additional 里再造一个电池字段——从模板层杜绝"锅容量/电池容量混淆"类问题);`label_en` 必填(英文红线);key 用 snake_case 英文。
- 端点:GET/PUT `/k/categories/{id}/spec-template`,POST `.../spec-template/draft`(AI 起草)。

## 2. 1688 粘贴解析(省手关键)
- K 产品详情规格区加端点 POST `/k/products/{id}/specs/parse-paste`:入参 `{raw_text}`(运营从 1688 详情页整段复制的中文规格,格式不限:表格文本/键值行/杂乱段落)。
- 服务端把 **raw_text + 该产品叶子类目的模板** 一起喂 AI:按模板对号入座(翻译/归一单位/数值提取),返回 `{matched: {key: {value, raw_value, source_label}}, unmatched_lines: [...], missing_required: [...]}`。
- **只解析不落库**——前端展示解析结果,运营确认/修正后走既有保存通道(现有 specs 手动保存端点)。AI 拆不出的字段留空(**不编造**,证据铁律);unmatched 行展示给运营自行判断。
- 解析结果中的 `source_label` 存原始中文标签(证据留痕),`label_en` 用模板的。
- 复用既有:标签中译英、单位归一(structured_specs 归一化)、CJK 出口门。

## 3. 必填校验门
- 产品保存规格时:按其叶子类目模板校验 `required` 字段——缺失则**保存成功但标记** `specs_incomplete`(缺什么列清单),并在 **K→P 上架门禁**(gate_blockers)加一条:模板必填未齐 → 阻断上架(与价格缺失同级)。
- 无模板的类目(还没起草)不阻断——保持现行行为,避免旧品全被卡死;但在产品页提示"该类目还没有规格模板,建议先起草"。

## 4. 前端(K 产品详情 · 规格区改造)
- 规格区按模板渲染表单:中文标签 + 单位 + 必填星标;模板外的额外字段仍可自由添加(落 additional_specs)。
- 顶部一个**粘贴框 + 「解析」按钮** → 调 #2 → 解析结果预填表单(高亮 AI 填的,运营可改)→ 保存。
- 类目无模板时:显示「AI 起草模板」按钮 → 调 #1 draft → 进入模板审定 UI(简单的字段列表增删改)→ 批准。
- 模板管理入口也放在类目管理页(已有类目树 UI)。

## 硬约束
- 别造假:解析拆不出=留空;AI 起草的模板必须人工 approve 才生效。
- 新增端点全部登记前端代理白名单(tests/frontend/proxy-allowlist-drift 会抓)。
- 迁移:先 `ls backend/alembic/versions/` 找 head 单链分叉;迁移不自动跑(Claude 手动执行)。
- 测试 `bash scripts/run_backend_tests.sh unit` 全绿 + 前端 `npm test -- --run` 全绿。
- 七个对比产品不动;fail-safe/品牌硬门不变。

## 交付
本地提交 + 双端测试绿 + 每任务一句根因/修法。完成后 Claude 用一个真实产品(用户手动 1688 粘贴)端到端验证。
