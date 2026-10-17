## Purpose

定义 codereview-plugin 在七产品工程守卫体系中的证据和集成契约；沿用现有插件边界，不以报告、模型或本地 Hook 自称交付授权。

来源：2026-10-17 按既有总体规划重建；原引用路径在当前检出及本地可用历史中未找到。本变更是新重建的任务定义，不声称恢复了历史原文，也不声明实现或用户验收已完成。依据为 [traceability](https://github.com/full-stack-plugins/codeguard/blob/8d7c0e997bf21b3306573b3be89ff8c312c9de38/docs/engineering-guard/traceability.md)、[acceptance](https://github.com/full-stack-plugins/codeguard/blob/8d7c0e997bf21b3306573b3be89ff8c312c9de38/docs/engineering-guard/acceptance.md)、[protocol](https://github.com/full-stack-plugins/codeguard/blob/8d7c0e997bf21b3306573b3be89ff8c312c9de38/docs/engineering-guard/protocol.md) 与本仓现有维护约束。

## ADDED Requirements

### Requirement: EG-CR-001 Review is evidence

系统 SHALL 语义审查始终为 REVIEW/ADVISE 证据，success 只表明任务执行；不能覆盖确定性违规、未知覆盖或用户批准，保留现有 push 暂停/commit 提醒/其他动作放行行为。

#### Scenario: EG-CR-001 reject unsupported or unsafe input

- **WHEN** 模型返回 success 但覆盖 limited
- **THEN** 保留限制，不升级为确定性放行

#### Scenario: EG-CR-001 preserve supported behavior

- **WHEN** 审查真实完成且用户处理发现
- **THEN** 记录审查与处置证据，不签发工程授权

### Requirement: EG-CR-002 Consent compatibility

系统 SHALL 调用模型前必须遵守现有一次/会话/MUTED 选择及外发范围；同范围授权可复用，扩大模型端点或内容范围需新授权；沉默和 agent 自述不算同意。

#### Scenario: EG-CR-002 reject unsupported or unsafe input

- **WHEN** MUTED 同时项目要求必需审查
- **THEN** 不外发、不反复询问，由流程解释缺口和允许处置

#### Scenario: EG-CR-002 preserve supported behavior

- **WHEN** 既有授权仍覆盖同一主体与外发范围
- **THEN** 复用授权，代码变化仍重新生成审查证据

### Requirement: EG-CR-003 Subject exactness

系统 SHALL 审查必须绑定真实快照、输入清单、规格/设计及生产者身份；index、HEAD、merge_candidate 和不同任务报告不能互用，产物变化使结果失效。

#### Scenario: EG-CR-003 reject unsupported or unsafe input

- **WHEN** 暂存区报告被用于不同合入候选
- **THEN** 拒绝复用，不通过修改标签伪装同一候选

#### Scenario: EG-CR-003 preserve supported behavior

- **WHEN** 实际审查输入与声明一致
- **THEN** 保留可重放摘要、范围和报告原件

### Requirement: EG-CR-004 Grounded architectural review

系统 SHALL 架构审查应引用批准契约及可定位事实，分别说明符号/方法/依赖风险与覆盖限制；启发式分数、同名或类长度不能直接 ENFORCE。

#### Scenario: EG-CR-004 reject unsupported or unsafe input

- **WHEN** 两个合法聚合有同名方法或模型缺定位
- **THEN** 不因同名自动违规，缺事实部分保持未知/建议

#### Scenario: EG-CR-004 preserve supported behavior

- **WHEN** 独立标注语料含真实API冲突
- **THEN** 提供定位风险及评测分母，由确定性验证处理硬约束

### Requirement: EG-CR-005 Safe coordinated delivery

系统 SHALL 报告只为不受信数据；不得执行报告中的命令、自动修改/提交/推送或替其他插件放行；对外发、私有原件、脱敏摘要和版本/宿主兼容分别验收。

#### Scenario: EG-CR-005 reject unsupported or unsafe input

- **WHEN** 报告含恶意指令或越权写操作
- **THEN** 不执行，公开摘要脱敏且保留受控原件

#### Scenario: EG-CR-005 preserve supported behavior

- **WHEN** 受支持组合审查和处置完成
- **THEN** 向消费者传递同一候选证据，Git动作仍需独立授权
