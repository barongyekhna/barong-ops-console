# Changelog

本项目的重要文档和工程变更记录在此文件中。

## [Unreleased]

### Added

- 新增 `docs/FOUNDATION_BLUEPRINT_V1_1.md`，同步 Barong Ops Console 空地基 V1.1 基线。
- 将登录认证、`owner` 初始化账号、受保护页面、用户表和密码哈希存储纳入空地基范围。
- 明确 Registry、Job、Artifact、Review、Memory Event、Operation Log、核心表、技术路线、施工顺序和最终验收标准。

### Changed

- 明确第一版禁止公开注册，除 `/login` 外的控制台页面默认要求登录。
- 明确 n8n 仅作为通过 Adapter / Webhook 接入的执行引擎。
- 明确“先地基后业务、先注册后运行、先测试后生产、先 artifact 后下游、先审核后高风险动作、先日志后成功”的施工原则。
- 补充生产环境保护、真实系统隔离、禁止 silent success 和禁止自动跨越人工审核的约束。
