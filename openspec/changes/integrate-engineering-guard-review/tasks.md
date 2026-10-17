# codereview-plugin 工程守卫集成任务

来源：2026-10-17 按既有总体规划重建；原引用路径在当前检出及本地可用历史中未找到。本变更是新重建的任务定义，不声称恢复了历史原文，也不声明实现或用户验收已完成。依据为 [traceability](https://github.com/full-stack-plugins/codeguard/blob/8d7c0e997bf21b3306573b3be89ff8c312c9de38/docs/engineering-guard/traceability.md)、[acceptance](https://github.com/full-stack-plugins/codeguard/blob/8d7c0e997bf21b3306573b3be89ff8c312c9de38/docs/engineering-guard/acceptance.md)、[protocol](https://github.com/full-stack-plugins/codeguard/blob/8d7c0e997bf21b3306573b3be89ff8c312c9de38/docs/engineering-guard/protocol.md) 与本仓现有维护约束。

状态：全部待实施。完成状态只在本账本维护；实现与所需真实环境验证齐备后才能勾选。每行列出的依赖是前置验收义务，不把文档创建当成前置实现完成。

## 1. 实施与验证

- [ ] 1.1 **EG-R01** [owner=codereview-plugin] 冻结advisory报告/执行成功边界与既有push/commit/other三分流，不接管专业确定性规则。 依赖：EG-K01。规格：EG-CR-001, EG-CR-005。

- [ ] 1.2 **EG-R02** [owner=codereview-plugin] 接独立来源的外发授权验证并保持ONCE/SESSION/MUTED；授权复用、范围扩大、伪造actor及静默拒绝均验收。 依赖：EG-R01, EG-K09。规格：EG-CR-002。

- [ ] 1.3 **EG-R03** [owner=codereview-plugin] 绑定真实index/commit/merge_candidate与任务/规格身份；保留原始审查输入及输出摘要，跨候选冒用必须拒绝。 依赖：EG-R01, EG-K04。规格：EG-CR-003。

- [ ] 1.4 **EG-R04** [owner=codereview-plugin] 提供最小可独立验收的版本化审查证据provider；真实审查成功但limited仍非工程通过，供首批联合验收消费。 依赖：EG-R01, EG-R03。规格：EG-CR-001, EG-CR-005。

- [ ] 1.5 **EG-R05** [owner=codereview-plugin] 接批准设计与CodeGraph事实的定位上下文和覆盖限制；无事实/旧索引仍是未知，不以模型分数强制放行。 依赖：EG-R03, EG-K21。规格：EG-CR-004。

- [ ] 1.6 **EG-R06** [owner=codereview-plugin] 实现审查发现/用户处置/恢复动作投影与日志脱敏，不执行报告指令，不自动提交推送。 依赖：EG-R02, EG-R04。规格：EG-CR-001, EG-CR-005。

- [ ] 1.7 **EG-R07** [owner=codereview-plugin] 完成版本化只读证据接口、N/N-1协议及未知major拒绝，保留当前OCR和宿主授权行为。 依赖：EG-R03, EG-K18。规格：EG-CR-002, EG-CR-003。

- [ ] 1.8 **EG-R08** [owner=codereview-plugin] 以独立标注语料验证合法协调/同名/真实API冲突/独立任务，公开误报漏报和覆盖分母。 依赖：EG-R05, EG-K22。规格：EG-CR-004。

- [ ] 1.9 **EG-R09** [owner=codereview-plugin] 实测当前候选、真实模型调用及用户处置全链路，恶意报告与越权反例验证，跨入口结果一致。 依赖：EG-R06, EG-R08。规格：EG-CR-001, EG-CR-003, EG-CR-005。

- [ ] 1.10 **EG-R10** [owner=codereview-plugin] 完成真实宿主、外发授权、固定OCR/runtime制品与发布/回滚矩阵，技能来源与市场版本验证后发布。 依赖：EG-R07, EG-R09, EG-K20。规格：EG-CR-002, EG-CR-005。
