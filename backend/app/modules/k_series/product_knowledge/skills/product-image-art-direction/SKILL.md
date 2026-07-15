---
name: product-image-art-direction
description: 【通用 · 产品图风格指令生成】读取一份已完成的亚马逊 Listing 或独立站产品页文案，分析产品定位后输出一整套作图风格要求（Art Direction）：图片张数与分工排布、风格原型、色调光线、构图镜头语言、每张图的英文 prompt 风格块与负面词——可直接拼进 image 模型（即梦/Imagen/Flux 等）的 prompt，确保整套图风格统一、高质量、符合平台规则。只要用户提到产品图、作图、图片风格、主图、A+ 图、场景图、细节图、图片 prompt、出图要求、image 模型生图，或刚生成完文案要配图，都应使用本 skill。
---

# 产品图风格指令生成（文案 → Art Direction → image 模型 prompt）

## 0. 品牌视觉家规（Barong Yekhna · 硬约束 · 覆盖下方 Step 2 的风格原型选择）

本项目（Barong Yekhna 独立站 / everything store）**全线共用同一套视觉家规**，不再"一个产品挑一个风格原型"。原因：品类会无限扩张（今天冷疗机、明天水杯、后天露营灯），只有"呈现方式绝对统一"才能让多品类看起来是**一个有格调的品牌**而不是杂货铺。**秩序不来自统一颜色，来自统一画框——除了产品本身，一切都是常量。**

**遇到 Barong Yekhna 的产品时，Step 2 直接锁定为下面的家规，不做六选一。**

### 心法（一句话）
让"呈现方式"绝对刚性，"产品"才可以绝对自由。背景 / 打光 / 构图 / 阴影全部写死，产品的**形状与颜色是页面上唯一允许变化的变量**。

### 两种镜头（只有这两种，共享同一套光与色的语法）

**A. 干净产品图（主图 + 画廊图 / gallery）——管 CTR、网格陈列。** 固定英文风格块（每条此类 prompt 末尾必拼，一字不改）：
```
STYLE BLOCK (Barong Yekhna house rule — clean product shot): Premium e-commerce product photography. Single product centered on a seamless BRIGHT warm off-white studio background (near #F7F6F4), the background lit two stops brighter than the product so the ground is clean bright white, never grey. Soft, even, diffused light from the upper left; a soft subtle contact shadow directly beneath the product. Generous negative space, product centered at a consistent scale. Crisp focus, true-to-life vivid saturated product colour. Clean, airy, high-end catalog aesthetic. No props, no text, no clutter.
CONSISTENCY: same product as the reference image — do not alter product shape, colour, or markings.
```

**B. 生活场景图（scene / description）——管"想要"、告诉陌生顾客怎么用。** 产品放进真实环境，但**必须共享同一套"明亮、暖、柔"的光与色**：明亮通透的室内/场景、上方左侧柔和自然光、暖调中性色、浅景深、克制不杂乱、真实产品颜色。禁止暗调、禁止冷调、禁止杂乱道具。目标：场景图和干净产品图放一起像"同一个摄影师、同一天拍的"。

### 家规红线（高于下方"红线"，最高优先级）
- 干净产品图背景**永远明亮暖白**（#F7F6F4 档），**绝不允许发灰**（灰=打光没到位、背景没比产品亮 2 档，不是风格）。
- 全线**不切换风格原型**：不管什么品类都用这套家规。
- 产品颜色**据实、鲜艳、饱和**——它是唯一变量，别压灰压暗。

> 技术备注：本家规已在代码层强制——K→I 出图前，主图/画廊图的 prompt 会自动追加上面的 STYLE BLOCK 作兜底（AI 跑偏也拉回）。你写 prompt 时也照家规写，双保险。

## 为什么需要这份 Art Direction（原理一页纸）

1. **每个图位都有唯一使命，按漏斗排序**：主图管点击（CTR）→ 信息图管看懂 → 场景图管想要 → 尺寸/对比图管打消疑虑 → 开箱/UGC 图管信任。一张图干两件事 = 两件都干不好。
2. **移动端前 3 张定生死**：约 70-80% 流量在手机上，多数买家不会滑过第 3 张图。主图 + 最强利益信息图 + 最佳场景图必须能独立完成整个销售。
3. **AI 出图最大的坑是产品本体失真**（错误的按键、走样的 logo、乱码文字）——这是电商 AI 图的头号杀手。铁律：**产品本体永远用真实照片，AI 只负责背景、场景、光线**；整套图靠固定的风格块 + 固定 seed + 参考图保持一致。
4. **风格原型必须匹配"品类惯例 × 价格档位 × 人群向往"**：高价产品配廉价明亮风 = 视觉上自降身价；低价产品配暗调高级风 = CTR 被品类惯例惩罚。
5. 数据支撑：场景化图片广告 CTR +40%（亚马逊官方）；UGC 风格图转化中位数 +19%（但 DTC 首图仍是棚拍质感赢）；360°/视频转化 +27-30%。来源与可信度分级见 [references/image-marketing-notes.md](references/image-marketing-notes.md)。

## 输入

必需：一份本项目生成的亚马逊 Listing 或独立站产品页文案（从中提取产品认知）。
追问用户（缺了会影响质量）：
- 有没有产品真实照片/3D 渲染源文件？（决定"AI 换背景"还是"全 AI 生成+人工校对产品细节"两种工作流）
- 价格档位（决定 premium vs value 视觉语言）
- 产品实物颜色/材质（文案里往往没有）
- 品牌是否已有视觉规范（品牌色/字体）

## 工作流

### Step 1 — 从文案提取产品 DNA

读文案，填出这张表（它驱动后面所有决定）：

| 维度 | 从文案哪里提取 |
|---|---|
| 品类与使用环境 | 标题、场景条 bullet |
| 目标人群（谁在用） | COSMO 人群条、Q&A |
| 核心使用场景 ×3 | 场景条、A+ 规划 |
| 可视化的数字卖点 | 各 bullet 的数字声明（这些就是信息图的文字） |
| 需要视觉化打消的疑虑 | 异议处理条、Q&A（尺寸、安装、兼容） |
| 价格档位与竞争定位 | 对比表、用户输入 |

### Step 2 — 选风格原型（六选一为主调，可加一个辅调）

| 原型 | 视觉语言 | 适用 |
|---|---|---|
| 明亮通透 Bright & Airy | 白/粉彩底、柔和日光、大留白 | 清洁美妆、母婴、食品、健康 |
| 暗调高级 Dark & Premium | 低调布光、深影、金色轮廓光、哑光石木 | 香氛、咖啡酒类、高端数码、轻奢 |
| 极简北欧 Minimal Scandinavian | 中性色、自然材质、极少道具 | 护肤、家居、服饰基础款 |
| 户外冒险 Outdoor & Adventure | 黄金时刻、真实地形、动感、风化质感 | 户外装备、运动（YETI/Patagonia 型） |
| 科技理性 Clinical & Tech | 冷调棚光、渐变底、爆炸图、参数标注 | 电子、仪器、科学向保健品 |
| 温暖居家 Cozy & Home | 暖色钨丝光、织物、有生活气的室内 | 蜡烛、床品、厨具、礼品 |

选择依据 = 品类惯例（去搜索结果页看头部竞品的主流风格）× 价格档 × 人群向往时刻。**选定后写死主调，整套图不换风格。**

### Step 3 — 排图片计划（平台决定张数与分工）

**亚马逊（填满 7-9 位，顺序即漏斗）：**

| # | 图位 | 使命 | 要点 |
|---|---|---|---|
| 1 | 主图（纯白底） | CTR | 见下方主图合规与技巧 |
| 2 | 核心利益信息图 | 看懂 | 3-5 个数字卖点标注，≤30 词，字号 ≥28pt@2000px |
| 3 | 主场景图 | 想要 | 目标人群的"向往时刻"，人物与人群画像一致 |
| 4 | 尺寸/比例图 | 疑虑 | 手持/身体/环境参照 + 标注尺寸（最强降退货图） |
| 5 | 对比图 | 疑虑 | vs 传统方案或竞品类型（不点名品牌） |
| 6 | 开箱/全家福 | 信任 | 所有内含物平铺，礼品感 |
| 7 | UGC 风格/细节特写 | 信任 | 手机摄影质感的真实使用，或材质微距 |
| 8-9 | 副场景/视频位 | 补充 | 建议用户补 360°或视频（转化 +27-30%） |

**独立站（5-8 张 + 技术要求）：**
- 首图 Hero：棚拍质感的"人 + 产品使用中"（与亚马逊白底逻辑相反）
- 2-3 张场景图（覆盖不同人群/场景）、1 张细节特写、1 张比例图、1-2 张 UGC 风格
- 技术随附要求：文件名含关键词（`portable-camping-shower-led-display.webp`）、alt 文本 60-90 字符、WebP/AVIF、首图不许懒加载并加 `fetchpriority="high"`

### Step 4 — 写全局风格块（英文，每条 prompt 都要拼在末尾）

固定格式（按 主体→表面→道具→背景→光线→情绪→相机 的语序服务 image 模型）：

```
STYLE BLOCK: [archetype] commercial product photography. Palette: [3-5 colors].
Lighting: [具体光线语言]. Surfaces/props: [材质词]. Camera: [镜头语言].
Mood: [2-3 个情绪词]. Ultra-detailed, 8k, professional e-commerce photography.
NEGATIVE: text artifacts, distorted product details, warped logo, extra buttons,
plastic-looking materials, oversaturated, cluttered composition, watermark.
CONSISTENCY: same product as reference image, do not alter product shape/color/markings.
```

光线词库：soft diffused daylight / three-point studio lighting / warm golden-hour side light / moody low-key spotlight / backlit rim light / soft grounded shadow。镜头词库：85mm f/2.8 / macro / top-down flat lay / three-quarter angle eye level / shallow depth of field。

### Step 5 — 写每张图的 prompt 骨架（英文）+ 中文制作备注

每张图输出三行：
1. **PROMPT**：场景描述（主体→表面→道具→背景→光线→相机），末尾拼全局风格块
2. **OVERLAY TEXT**（如有）：图上文字内容（英文，来自文案的数字卖点；文字建议后期加而不是让 AI 生成——AI 文字乱码是高频翻车点）
3. **制作备注**（中文）：这张图的使命、375px 手机预览自检点、合规注意

### Step 6 — 合规与质检清单（附在交付末尾）

**亚马逊主图红线（机器审查，零容忍）**：纯白 RGB(255,255,255)；产品占画面 ≥85%；无文字/logo/水印/角标/边框；不出现未随货发售的道具；最长边 ≥1600px（建议 2000px+ 以启用缩放）；竖向构图在手机上显得更大。**合法技巧**：包装盒上的文字是产品的一部分（可以把包装设计成广告位）；全部内含物可以和包装同框；低机位 3/4 角度 + 落地软影增强体积感。
**AI 图政策**：AI 场景图用于副图可以，主图不要用纯 AI 合成场景；产品像素保持真实；比例不得误导。
**全套自检**：产品在每张图里外观 100% 一致（对照真实参考图逐张核对按键/logo/接口）；信息图文字 ≤30 词且 375px 宽度下可读；前 3 张能否独立卖出这个产品？

## 交付格式

```
# [产品名] 作图风格指令（Art Direction）
## 1. 产品 DNA 表（从文案提取）
## 2. 风格原型与选择理由
## 3. 图片计划表（张数、顺序、每张的使命）
## 4. 全局风格块（英文，可直接拼 prompt）
## 5. 逐张 prompt 骨架 + 图上文字 + 中文制作备注
## 6. 一致性控制（seed/参考图/产品细节核对点)
## 7. 合规与质检清单
## 8. 需要用户提供的素材清单
```

## 红线

让 AI 重新生成产品本体（细节失真 = 差评与退货）；让 AI 直接生成图上文字（乱码高发，文字后期加）；主图用 AI 合成场景或加违规文字角标；整套图风格漂移（每张换风格）；信息图塞 >30 词；高价产品配廉价视觉 / 低价产品配暗调风。
