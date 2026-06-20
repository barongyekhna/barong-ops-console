# System Modules Explained - Human Readable

这份说明书只解释当前系统里各个模块“是做什么的”。它不是技术设计文档，也不改变任何代码、后端、UI、权限或数据库。

这里的 “Limited” 可以理解为：页面或模块已经能看见、能记录一些数据，部分地方也能创建记录或做简单操作，但还不是完整成熟的产品功能。常见原因包括：

- 功能未完全接入：模块还没有接到完整业务流程或真实执行链路。
- UI 未产品化：页面更像运维/管理台，不是给业务人员长期使用的完整产品界面。
- 权限未开放：只有 owner、admin 或具备特定权限的人能看或操作。
- backend 能力未完全暴露：后端有一些基础能力，但没有把完整能力开放到前端页面。

## Jobs / Workflows / Agents 的关系

- Jobs 是“任务入口”：有人或系统想做一件事，就先创建一个 Job。
- Workflows 是“执行流程”：Job 要按什么步骤做、走哪条流程，由 Workflow 表达。
- Agents 是“执行者”：真正负责接这个任务、按流程去做事的执行单位。

完整例子：

公司要“准备一个产品上架资料”。

1. 运营人员创建一个 Job：任务是“准备产品 A 的上架资料”。
2. 这个 Job 选择一个 Workflow：流程是“收集资料 -> 检查风险 -> 生成产物 -> 等待审核”。
3. 系统把这个 Job 分给一个 Agent：这个 Agent 负责按流程处理资料。
4. Agent 执行后可能生成 Artifact：例如“产品资料包”。
5. 如果风险较高，系统创建 Approval 或 Review：让负责人批准或审核。
6. 执行过程产生 Logs、Errors、Memory Events：方便之后追踪发生了什么。

也就是说：Jobs 提出“要做什么”，Workflows 规定“怎么做”，Agents 负责“谁来做”。

## Business Modules

### 🟣 Jobs

### 🧠 它是干什么的（用最简单人话）

Jobs 是系统里的“任务入口”。任何要被系统处理的事情，都可以先变成一个 Job。它记录任务编号、属于哪个模块、要走哪个流程、交给哪个执行者、当前状态是什么。

### 🟡 一个现实世界例子

运营人员想让系统准备一份产品上架资料，就创建一个 Job：任务名是“准备产品 A 上架资料”，状态先是 pending，后面可能变成 running、waiting review 或 completed。

### ⚙️ 谁会用它（owner / admin / system）

主要是 admin 和 system 使用。admin 用它查看、创建或推进任务记录；system 用它记录自动化任务状态；owner 用它做最终权限和治理检查。

### ❗为什么显示 “Limited”

- 功能未完全接入：当前 Jobs 更多是任务记录和状态事件，不代表任务一定已经接入真实执行系统。
- UI 未产品化：页面是通用管理台，可以创建和查看记录，但还不是业务人员的一站式任务中心。
- 权限未开放：需要 jobs.read / jobs.create 等权限，不是所有用户都能操作。
- backend 能力未完全暴露：后端有任务、事件、状态边界，但完整重试、取消、真实执行编排等能力没有全部产品化到页面。

### 🟣 Workflows

### 🧠 它是干什么的（用最简单人话）

Workflows 是“执行流程”。它告诉系统：一个任务要按照什么步骤执行、使用什么执行引擎、是否需要回调、失败后怎么重试。

### 🟡 一个现实世界例子

“产品上架准备流程”可以是一个 Workflow：先检查产品资料，再生成资料包，再等待人工审核，最后把结果记录下来。

### ⚙️ 谁会用它（owner / admin / system）

主要是 admin 和 system 使用。admin 维护流程登记信息；system 在创建 Job 或执行 Job 时引用流程；owner 负责决定哪些流程可以开放。

### ❗为什么显示 “Limited”

- 功能未完全接入：当前更多是流程登记和元数据管理，不等于完整工作流引擎已经在页面里运行。
- UI 未产品化：页面适合管理流程记录，但还不是可视化流程设计器。
- 权限未开放：通常需要 modules.read / jobs.create 等权限。
- backend 能力未完全暴露：后端有 Workflow Registry 和任务引用能力，但完整流程编排、外部执行器运行状态、失败恢复等没有全部暴露成产品功能。

### 🟣 Approvals

### 🧠 它是干什么的（用最简单人话）

Approvals 是“批准关”。当系统准备做一件可能有风险的事时，可以先创建审批请求，由有权限的人批准或拒绝。

### 🟡 一个现实世界例子

系统准备执行“真实发布产品资料”前，先发起 Approval。负责人看见风险等级、原因和动作内容后，选择批准或拒绝。

### ⚙️ 谁会用它（owner / admin / system）

主要是 owner 和 admin 使用。system 会自动创建审批请求；admin 可以处理普通审批；owner 负责更高权限或高风险审批。

### ❗为什么显示 “Limited”

- 功能未完全接入：当前批准或拒绝主要是“记录决策”，不代表批准后一定自动触发真实业务动作。
- UI 未产品化：页面能看、能创建、能批准/拒绝，但还不是完整审批工作台。
- 权限未开放：需要 reviews.read / reviews.approve 等治理权限。
- backend 能力未完全暴露：后端有审批请求和决策记录能力，但审批策略、自动执行解锁、完整审批链路没有全部开放到 UI。

### 🟣 Reviews

### 🧠 它是干什么的（用最简单人话）

Reviews 是“人工复核”。它用于让人检查某个任务、产物或结果是否合格，并留下审核意见。

### 🟡 一个现实世界例子

系统生成了“产品 A 上架资料包”，审核人员在 Reviews 里检查内容，然后选择通过、拒绝或要求修改。

### ⚙️ 谁会用它（owner / admin / system）

主要是 admin 和 owner 使用。system 可以创建待审核记录；admin 做日常审核；owner 处理关键或高风险审核。

### ❗为什么显示 “Limited”

- 功能未完全接入：当前可以创建审核记录和记录决策，但不等于完整人工派单、领取、升级、撤销流程都已产品化。
- UI 未产品化：页面是通用记录管理界面，不是成熟的审核队列产品。
- 权限未开放：需要 reviews.read / reviews.approve 等权限。
- backend 能力未完全暴露：后端具备基础 Review 记录能力，但完整审核流转、角色隔离和后续自动动作没有全部暴露到前端。

### 🟣 Artifacts

### 🧠 它是干什么的（用最简单人话）

Artifacts 是“任务产物登记处”。系统执行任务后产生的结果，例如文件、报告、资料包、截图或结构化结果，都可以登记成 Artifact。

### 🟡 一个现实世界例子

一个 Job 生成了“产品 A 上架资料包”。Artifacts 里会登记这个资料包的名称、类型、属于哪个 Job、存储引用和当前状态。

### ⚙️ 谁会用它（owner / admin / system）

主要是 admin 和 system 使用。system 写入产物记录；admin 查看产物并发起审核；owner 关注高风险产物的治理。

### ❗为什么显示 “Limited”

- 功能未完全接入：当前主要登记产物元数据，不代表真实文件存储、预览、下载、版本管理都已经完整接入。
- UI 未产品化：页面能登记、查看和发起 Review，但不是完整文件资产管理系统。
- 权限未开放：需要 artifacts.read / artifacts.create 等权限。
- backend 能力未完全暴露：后端有 Artifact 记录边界，但真实存储 provider、文件生命周期和完整版本能力没有全部暴露到 UI。

## System Modules

### 🟣 Dashboard

### 🧠 它是干什么的（用最简单人话）

Dashboard 是“系统总览”。它把系统健康、用户、组织、审批、日志和执行状态放在一个入口里，让管理者快速知道系统现在是否正常。

### 🟡 一个现实世界例子

负责人早上打开 Dashboard，看见系统健康正常、当前有 3 个待审批、最新日志没有失败，就知道今天可以继续运行。

### ⚙️ 谁会用它（owner / admin / system）

主要是 owner 和 admin 使用。owner 看整体状态；admin 看日常运维情况；system 提供健康、日志、审批等数据。

### ❗为什么显示 “Limited”

- 功能未完全接入：Dashboard 目前从多个接口拼出状态，不是一个完整专用的运营分析后台。
- UI 未产品化：它是运维总览，不是完整 BI 报表或业务驾驶舱。
- 权限未开放：部分数据依赖用户、审批、日志等权限，没有权限时只能看到受限状态。
- backend 能力未完全暴露：健康、日志、审批等数据分散在不同后端能力里，完整聚合 API 和深度分析还没有全部暴露。

### 🟣 Modules

### 🧠 它是干什么的（用最简单人话）

Modules 是“系统功能地图”。它告诉你当前工作区有哪些产品区域、哪些能用、哪些被隐藏、哪些只有部分能力，以及每个模块接了什么权限和 API。

### 🟡 一个现实世界例子

admin 想知道“Products 为什么不能完整使用”，就到 Modules 里看：它是否可见、权限是否满足、后端 API 是否接上、动作是否准备好。

### ⚙️ 谁会用它（owner / admin / system）

主要是 owner 和 admin 使用。owner 管控模块开放边界；admin 查看模块状态和资源记录；system 通过模块注册信息决定能力可见性。

### ❗为什么显示 “Limited”

- 功能未完全接入：当前模块地图和资源记录已经存在，但还不是完整 Module Manifest v1 的正式产品体系。
- UI 未产品化：页面偏控制台和注册表，不是业务模块商城或配置向导。
- 权限未开放：通常需要 modules.read / modules.manage 权限。
- backend 能力未完全暴露：后端有模块注册、可见性、绑定等基础能力，但完整生命周期、安装、升级、下线、依赖管理没有全部产品化。

### 🟣 Settings

### 🧠 它是干什么的（用最简单人话）

Settings 是“控制面状态页”。它展示执行 provider、模块 adapter、上线闸门、生产就绪检查和策略映射，不是普通意义上的“随便改系统设置”页面。

### 🟡 一个现实世界例子

上线前，admin 打开 Settings，看 live gate 是否通过、生产检查是否 ready、有哪些 provider 和 adapter 被登记。

### ⚙️ 谁会用它（owner / admin / system）

主要是 owner 和 admin 使用。owner 决定上线策略；admin 查看配置状态；system 根据 provider、adapter 和 live gate 决定是否允许执行。

### ❗为什么显示 “Limited”

- 功能未完全接入：当前 Settings 更偏状态汇总，不是完整设置中心。
- UI 未产品化：页面展示 provider、adapter、policy 和 readiness，但没有完整编辑、审批、变更历史工作流。
- 权限未开放：通常需要 settings.read 或相关控制面权限。
- backend 能力未完全暴露：后端的执行 provider、adapter、live gate 能力分散在不同接口，完整配置写入和治理流程没有全部开放。

### 🟣 Errors

### 🧠 它是干什么的（用最简单人话）

Errors 是“系统问题记录”。它记录系统运行中出现的问题，例如某个任务失败、某个模块报错、某次操作没有成功。

### 🟡 一个现实世界例子

一个 Job 在生成资料包时失败，系统登记一条 Error：错误代码、严重程度、关联的 Job、错误消息和细节。

### ⚙️ 谁会用它（owner / admin / system）

主要是 admin 和 system 使用。system 自动写入错误；admin 排查和登记问题；owner 关注高风险或反复出现的问题。

### ❗为什么显示 “Limited”

- 功能未完全接入：当前主要是错误元数据记录，不是完整事故处理平台。
- UI 未产品化：页面可记录和查看错误，但没有完整告警、分派、关闭、复盘流程。
- 权限未开放：通常依赖 operation_logs.read 等系统观察权限。
- backend 能力未完全暴露：后端有错误记录和查询边界，但完整确认、处理状态流转、告警联动没有全部产品化。

### 🟣 Memory Events

### 🧠 它是干什么的（用最简单人话）

Memory Events 是“长期上下文记录”。它记录对以后有价值的事实，例如某个任务发生了什么、某个对象的重要状态、某条需要保留的观察。

### 🟡 一个现实世界例子

系统发现某个产品资料连续两次审核失败，于是记录一条 Memory Event：这个产品资料需要重点关注。

### ⚙️ 谁会用它（owner / admin / system）

主要是 system 和 admin 使用。system 自动写入长期上下文；admin 查看和补充记录；owner 关注关键历史事实。

### ❗为什么显示 “Limited”

- 功能未完全接入：当前 Memory Events 是记录型能力，不是完整 AI 记忆、自动推理或知识库产品。
- UI 未产品化：页面能创建和查看记录，但不是可搜索、可治理、可复用的知识管理界面。
- 权限未开放：通常依赖 operation_logs.read 等系统观察权限。
- backend 能力未完全暴露：后端有受控创建和查询边界，但完整记忆检索、自动关联、生命周期管理没有全部暴露。

### 🟣 Logs

### 🧠 它是干什么的（用最简单人话）

Logs 是“系统流水账”。它记录系统做过什么、结果是什么、有没有错误，并从日志里整理出 trace、告警候选和异常信号。

### 🟡 一个现实世界例子

admin 想查某个 Job 为什么失败，就打开 Logs，看最近操作记录、错误码、trace ID 和相关动作。

### ⚙️ 谁会用它（owner / admin / system）

主要是 admin 和 system 使用。system 自动写入日志；admin 排查问题；owner 审计关键操作。

### ❗为什么显示 “Limited”

- 功能未完全接入：当前 Logs 主要展示最近操作，并从最新页面数据推导 trace 和告警候选，不是完整审计搜索系统。
- UI 未产品化：页面能查看日志、trace group、alert candidate 和 anomaly signal，但没有完整过滤器、保存查询、深度钻取。
- 权限未开放：需要 operation_logs.read 权限。
- backend 能力未完全暴露：后端有 operation logs 基础查询，但完整审计查询引擎、追踪图、异常检测结果没有全部产品化到 UI。

### 🟣 Extensions

### 🧠 它是干什么的（用最简单人话）

Extensions 是“扩展能力区”。它不是单个业务页面，而是放置可插拔能力的分组，例如 Agents 和 Products。

### 🟡 一个现实世界例子

公司以后想接入新的执行者、产品适配器或外部系统入口，这些能力会放在 Extensions 下面，而不是混在核心系统页面里。

### ⚙️ 谁会用它（owner / admin / system）

主要是 owner、admin 和 system 共同使用。owner 决定能装哪些扩展；admin 查看和管理扩展记录；system 根据扩展登记来决定是否能调用。

### ❗为什么显示 “Limited”

- 功能未完全接入：Extensions 当前更像导航分组和能力容器，不是完整插件市场。
- UI 未产品化：没有独立的扩展安装、启用、卸载、版本管理页面。
- 权限未开放：扩展下的具体页面分别受 modules.read、products.read、jobs.create 等权限控制。
- backend 能力未完全暴露：后端有 adapter、agent、provider 等注册能力，但完整扩展生命周期没有全部暴露。

### 🟣 Agents

### 🧠 它是干什么的（用最简单人话）

Agents 是“执行者”。它记录哪些自动化执行单位存在、叫什么、能处理哪些模块、能跑哪些流程。

### 🟡 一个现实世界例子

系统里登记一个 Agent，叫 product-prep-agent。它只能处理 business.products 相关任务，并且只能走指定的产品准备 Workflow。

### ⚙️ 谁会用它（owner / admin / system）

主要是 admin 和 system 使用。admin 登记和查看执行者；system 给任务分配执行者；owner 控制哪些执行者可以被信任。

### ❗为什么显示 “Limited”

- 功能未完全接入：当前 Agents 主要是执行者注册记录，不代表真实机器人、外部 worker 或 AI agent 已完整运行。
- UI 未产品化：页面能登记 Agent、查看详情、创建关联 Job，但不是完整执行者监控中心。
- 权限未开放：通常需要 modules.read / jobs.create 等权限。
- backend 能力未完全暴露：后端有 Agent Registry 和任务关联能力，但完整健康检查、负载、执行日志、调度能力没有全部开放到 UI。

### 🟣 Products

### 🧠 它是干什么的（用最简单人话）

Products 是“产品能力入口”。当前它主要展示产品模块的 adapter 信息，并允许创建一个 metadata-only 的产品准备 Job。

### 🟡 一个现实世界例子

admin 在 Products 里看到 business.products 的 adapter 已登记，于是创建一个“准备产品资料”的 Job，但这个 Job 目前仍是元数据任务，不等于直接改真实商品系统。

### ⚙️ 谁会用它（owner / admin / system）

主要是 admin 和 system 使用。admin 查看产品适配器和创建准备任务；system 通过 adapter 信息判断是否有可用能力；owner 决定产品能力何时真正开放。

### ❗为什么显示 “Limited”

- 功能未完全接入：当前 Products 不是完整商品管理系统，也没有接入真实产品发布、库存、价格或外部电商写入。
- UI 未产品化：页面展示 adapter 和 action metadata，不是产品目录、商品编辑器或运营后台。
- 权限未开放：需要 products.read / jobs.create 等权限。
- backend 能力未完全暴露：后端主要暴露 module adapter registry 和 metadata-only Job 创建，完整产品 API、真实业务写入和外部系统集成没有开放。

