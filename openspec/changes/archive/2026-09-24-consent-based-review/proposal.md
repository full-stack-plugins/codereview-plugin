# Proposal

## Why

代码提交前需要结合需求和代码上下文的语义审查，但不应把可选的模型建议变成强制门禁，也不应反复打扰已拒绝的用户。需要独立插件管理授权、审查任务与证据，让智能体推进流程、Hooks 检查关键边界。

## What Changes

- 新建 `codereview-plugin`，提供 Codex、ZCode、Kimi 的插件适配与本地审查编排能力。
- 提交前提供“仅本次审查 / 当前会话自动审查 / 本会话不再提醒”三种选择；未明确授权不得调用模型。
- 将会话偏好与逻辑提交任务分开，支持重试、授权撤销、报告失效和成功提交后的任务关闭。
- 接入 Alibaba Open Code Review CLI 的正式接口：默认使用 Delegation Mode 让当前宿主智能体执行审查，可选使用 OCR-managed Mode 调用 OCR 配置的模型；两者均审查确定的提交内容快照并输出可验证的结构化报告。
- Hooks 只做快速状态检查与恢复提示；耗时审查由智能体显式启动，不依赖多个插件 Hook 的先后顺序。
- CodeReview 默认建议模式；跳过不等于通过，也不能绕过 FlowGuard 的显式策略或 CodeGuard 的检查。

## Capabilities

### New Capabilities

- `review-consent`: 授权范围、会话静默、一次性任务授权与撤销。
- `commit-review`: 提交快照、引擎执行、报告可信度与结果处置。
- `host-integration`: 多宿主 Hooks、智能体编排、独立运行与其他守卫的边界。

### Modified Capabilities

无；这是新项目，不修改现有 FlowGuard、CodeGuard 的规格或实现。

## Impact

- 新目录：`full-stack-plugins-repositories/codereview-plugin`。
- 拟新增 Python 编排内核、CLI、Hooks、插件专属技能、三端清单、测试和文档。通用上游审查规则不复制为插件内技能；引擎通过适配器调用。
- 运行依赖：Python、Git 和 `ocr`。Delegation Mode 不要求 OCR LLM 配置；OCR-managed Mode 要求用户明确配置 OCR。开发时本机仍是 OCR v1.6.5，上游已发布 v1.12.9，因此按能力探测而非单一版本字符串集成。没有调用模型，也没有读取或更改凭据。
- 可能的数据外发：审查变更及必要的仓库上下文会进入用户选择的模型服务，必须在授权时披露。
- 不安装或升级引擎，不自动创建远端仓库，不提交、推送、发布，不修改用户宿主配置。

## Non-goals

- 不实现新的 lint、编译器、测试框架或 FlowGuard 阶段管理器。
- 不把无问题、退出码 0 或模型“通过”作为安全保证。
- 不充当防恶意智能体的 OS 沙箱、Git 强制访问控制或服务端合并保护。
- 不自动修复代码、执行提交、推送或发布审查评论；这些操作需要各自授权。
