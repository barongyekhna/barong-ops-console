# Module / Agent / Workflow 合同

## 1. 目的

本合同规定 Barong Ops Console 中 Module、Agent 和 Workflow 的注册、标识、运行和协作边界。目标是保证所有能力可发现、可授权、可审计、可停用、可替换和可回滚。

未注册的 Module、Agent 或 Workflow 不得运行，也不得通过临时脚本、隐藏 Webhook 或直接数据库写入绕过 Registry。

## 2. Registry

### 2.1 Module Registry

Module Registry 是模块能力目录，登记一个业务或基础模块的责任边界、接口合同、权限、风险和生命周期状态。

每个模块使用稳定且唯一的 `module_id`。显示名称可以修改，但 `module_id` 不应因改名而变化。

### 2.2 Agent Registry

Agent Registry 是 Agent 能力目录，登记 Agent 的职责、允许使用的工具、数据范围、风险等级、版本、状态以及可调用的 Module 和 Workflow。

每个 Agent 使用稳定且唯一的 `agent_id`。Agent 不能凭自身判断扩大权限，也不能批准自己生成的高风险结果。

### 2.3 Workflow Registry

Workflow Registry 是工作流目录，登记执行入口、执行引擎、回调约定、输入输出、超时、重试、风险和版本。

每个 Workflow 使用稳定且唯一的 `workflow_id`。n8n 工作流只有在 Workflow Registry 中登记并启用后，才可由 Job Manager 调用。

## 3. 核心标识

- `module_id`：模块的稳定唯一标识。
- `agent_id`：Agent 的稳定唯一标识。
- `workflow_id`：工作流的稳定唯一标识。
- `job_id`：一次受控执行实例的唯一标识。

上述标识必须出现在相关 Job、Artifact、Review、Error、Memory Event、Operation Log 或 Context Packet 中，以便建立完整追踪链。不得用显示名称、n8n execution id 或临时文件名代替这些系统标识。

## 4. 注册声明最低要求

每个 Module、Agent 和 Workflow 必须声明以下合同项：

| 合同项 | 最低要求 |
| --- | --- |
| 职责 | 明确负责解决的问题和允许执行的动作。 |
| 不负责事项 | 明确排除范围、禁止动作和转交边界。 |
| 输入 schema | 字段、类型、必填项、约束、敏感级别和 schema 版本。 |
| 输出 schema | 结果结构、状态、Artifact 引用、错误表达和 schema 版本。 |
| 权限 | 可读写的数据域、可调用能力和外部系统权限。 |
| 风险等级 | 至少区分低、中、高风险，并关联审核策略。 |
| 版本 | 使用可比较版本，合同变更必须可追溯。 |
| 状态 | 至少支持 draft、active、disabled、deprecated。 |
| 依赖 | 声明依赖的 Module、Agent、Workflow、服务和最低版本。 |
| 产物类型 | 声明可能生成或消费的 Artifact 类型。 |
| 审核项类型 | 声明哪些结果必须生成 Review Item。 |
| 错误码 | 提供稳定、可分类、可检索的错误码集合。 |
| 健康检查 | 定义健康状态、检查方式、超时和失败判定。 |
| 回滚规则 | 定义停用、版本回退、补偿动作和不可回滚情况。 |

注册信息不完整、schema 不可验证、依赖未满足、状态非 active 或健康检查不通过时，不得启动新 Job。

## 5. Job 运行合同

所有执行必须由 Job Manager 创建 `job_id` 后开始。Job 至少绑定调用方、`module_id`、可选 `agent_id`、可选 `workflow_id`、输入 schema 版本、风险等级和追踪信息。

执行方只能通过 Job 事件报告状态，不得直接将任务标记为成功。成功必须同时满足输出 schema、Artifact 登记、必要 Review、Memory Event 和 Operation Log 规则。

重试必须关联原 Job 或明确记录父子关系，不能通过创建无关联任务掩盖失败。

## 6. 模块间协作

模块之间禁止直接修改彼此状态，也不得直接读取未完成任务的临时结果。跨模块协作只能通过以下受控对象：

- Job：表达待执行工作及其生命周期。
- Artifact：表达已登记、可版本化的任务产物。
- Review：表达人工审核请求、结论和放行条件。
- Memory Event：表达对长期上下文有意义的事实。
- Operation Log：表达谁在何时执行了什么动作及结果。
- Context Packet：表达经授权、可追踪、最小化的上下文交付。

直接调用内部实现、跨模块写表、共享可变内存、依赖临时文件路径或直接修改对方状态均属于合同违规。

## 7. 权限与风险

- 默认拒绝：合同未声明的权限一律不可使用。
- 最小权限：只授予完成职责所需的最小数据和动作范围。
- 高风险隔离：高风险结果必须创建 Review，生成方不得自批。
- 外部写操作：必须有明确 Workflow、审核策略、幂等键和 Operation Log。
- 停用生效：Registry 状态变为 disabled 后不得创建新 Job；在途 Job 按登记的回滚规则处理。

## 8. 错误与回滚

错误必须使用已登记错误码，并关联 `job_id` 及相关 Registry 标识。失败不能只写自由文本或只保留在外部执行引擎中。

回滚规则至少说明：

- 哪些状态转换可以回退。
- 已生成 Artifact 如何失效或保留历史。
- 外部副作用如何补偿。
- 在途 Job 如何取消、超时或人工接管。
- 回滚本身如何写入 Job Event、Memory Event 和 Operation Log。

无法自动回滚的动作必须在运行前标记风险并要求人工审核。

