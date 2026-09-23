## ADDED Requirements

### Requirement: 通用与插件专属技能分离
CodeReview 插件 SHALL 从独立技能仓及 Alibaba OCR 固定版本分发受管技能，并只在插件本地维护依赖其授权 CLI 的 harness。受管技能 MUST 与本地技能不重名，发布包 MUST 不依赖安装时访问外部仓库。

#### Scenario: 安装发布插件
- **WHEN** 宿主加载 CodeReview 发布包
- **THEN** 能发现两个官方 OCR 技能、五个通用增强技能和本地 harness，且每个受管技能可追溯来源 tag、commit 和内容摘要

### Requirement: 提交前授权不被通用技能绕过
候选提交审查 MUST 由插件 harness 的用户授权与隔离暂存快照入口协调。通用 OCR 技能的工作区、分支或提交审查 SHALL 是独立手动入口，不能自动继承插件授权或充当当前候选快照报告。

#### Scenario: AI 准备提交且未获授权
- **WHEN** 通用 OCR 技能也可用，但用户尚未选择本次或会话审查
- **THEN** 插件不调用模型、不读取候选供语义审查，并等待用户选择或保持静默

### Requirement: 外部来源完整性
插件 MUST 离线验证受管技能与锁中摘要一致，并在可联网时核对固定 tag 的 peeled commit 与上游目录。外部技能修改 MUST 从来源仓发布新版本，不得直接修改插件副本。

#### Scenario: 上游 tag 被移动或插件副本被改动
- **WHEN** CI 或维护者运行 vendor check
- **THEN** 检查失败并指出来源或具体技能，不能把漂移作为正常同步发布
