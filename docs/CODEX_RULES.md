# Codex 施工规则

## 1. 工作目录

- Codex 只能在 `/opt/barong-ops-console` 内施工。
- 未经老板明确批准，不得读取或修改工作目录之外的系统和项目文件。
- 每个任务必须遵守该任务给出的允许文件清单和禁止文件清单。
- 不得修改任何生产 Docker Compose 文件。

## 2. 每次任务流程

每次任务必须：

1. 先读取任务指定的基准文件和当前 Git 状态。
2. 先输出并维护 plan，再开始修改。
3. 只完成当前 Fxx 任务的明确范围，不允许跨任务顺手做功能。
4. 完成后输出 changed files。
5. 完成后输出 verification，包括实际运行的检查及结果。
6. 每次任务必须更新 `CHANGELOG.md` 的 Unreleased。
7. 未经要求不得 git commit；不得把未验证工作报告为完成。

## 3. 生产环境隔离

- 不允许碰生产 n8n、Filebrowser、MinIO 或白苏婉容器。
- 不得停止、重启、删除、修改或进入上述生产容器。
- 不得修改 `/opt/n8n`、`/opt/filebrowser`、`/opt/minio`、`/root` 或 `/var/lib/docker`。
- 不得连接真实 WooCommerce、真实 n8n workflow 或其他真实业务服务。
- 不得用生产系统做空地基测试。

## 4. 密钥与配置

- 不允许读取、打印、复制或修改真实密钥。
- 不允许创建真实 `.env`。
- 文档、代码、日志、测试和命令输出中不得包含真实密码、token、连接串或 Webhook secret。
- 后续如任务允许配置模板，只能创建不含秘密的 `.env.example`。

## 5. 空地基边界

- 不允许在空地基完成前接入真实业务。
- 未注册 Module、Agent 或 Workflow 不得运行。
- n8n 只作为执行引擎，不得作为状态真相源。
- Filebrowser / MinIO 只作为资产仓库。
- WooCommerce 只作为后续受控外部目标。
- 不得绕过 Job、Artifact、Review、Memory Event、Operation Log 或 Context Packet 直接跨模块改状态。

## 6. 修改与验证纪律

- 不删除用户已有改动，不修改当前任务清单外的文件。
- 不安装软件，不执行破坏性命令，不操作生产容器。
- 文档任务不得顺带编写后端、前端、migration 或真实环境配置。
- 所有结论以实际文件和检查输出为依据。
- 若检查失败，必须先修复或明确报告阻塞，不能宣称通过。

