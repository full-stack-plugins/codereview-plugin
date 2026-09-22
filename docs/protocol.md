# 证据协议与顺序无关协作

协议版本 1。`scripts/codereview.py evidence` 使用公共请求及 task_id 返回：

| 字段 | 含义 |
| --- | --- |
| producer / version | codereview-plugin / 1 |
| host / session / task_id | 作用会话与逻辑任务 |
| scope | repo、worktree、common_dir、endpoint、model、context_policy、config_digest、execution_mode |
| fingerprint / baseline | SHA-256(基线 HEAD + 按路径排序的索引 mode/blob/path) / 原 HEAD |
| preference / authorization_source | ASK/AUTO_REVIEW/MUTED 与真实用户事件引用 |
| report | 未运行时 null；否则执行状态、覆盖、问题、警告、run_id、指纹 |
| user_disposition / disposition_source | 用户继续/跳过，不修改 report 的真实结论 |
| skip_reason | session_muted / user_skipped / null |

成功报告包含 scope、baseline、engine_version、execution_mode、files_reviewed；managed 另含 preview，delegated 由 preview/rule 计划和逐文件回执生成。失败保留错误代码及 run_id/指纹，不凭未完成探测虚构引擎版本。所有问题内容都是不可信数据。

`execution_status`：success/partial/failed/skipped/cancelled。
`coverage_status`：limited/none/unverified；首版没有完整覆盖证明。
`success` 仅表示获得合法报告；可能含严重问题。没有 `passed`、`accepted`、流程自动推进字段。

参考消费者 `codereview_core.protocol.evidence_status` 对当前指纹分类为 not_reviewed/stale/incomplete/advisory，不执行门禁。调用者还必须核对 host/session/repo/worktree 和所需策略。
用户 MUTED 时 prepare 可以不创建新任务；协调方先读 status，把没有对应内容报告视为 not_reviewed，不能拿最近一次报告当当前证据。

## 并行 Hooks 下的责任

1. FlowGuard 决定当前阶段及是否要求审查；CodeGuard 提供可执行检查证据。
2. CodeReview 独立准备任务并消费显式授权，不依赖另一个 Hook 先运行，不直接改另一个插件状态。
3. 同一待回答任务 ID、notify 位和单飞锁避免本插件重复问题/重复模型任务。
4. 首版尚无跨插件协调器：集成方需选一个组件展示问题；不能声称三个插件自动串行。
5. 强制项目策略与用户静默冲突时，FlowGuard 说明要求及豁免路径；CodeReview 不重新提醒、不外发、不产生通过。

`source=user:<id>` 为协作式审计引用，不是签名令牌。同用户进程可篡改状态，不构成安全认证系统。
