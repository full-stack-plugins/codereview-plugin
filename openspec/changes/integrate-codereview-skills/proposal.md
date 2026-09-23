# 将 CodeReview 审查知识独立维护并接入插件

## Why

当前插件只分发一个本地编排技能，用户无法在同一插件中发现 Alibaba 官方 OCR-managed/Delegation 两种审查技能，也缺少需求上下文、发现核实和修复验证等专门工作流。插件代码与通用知识的所有权需要分离，且不能因此绕过提交前授权、暂存快照或会话静默。

## What Changes

- 建立 `full-stack-skills/codereview-skills`，先交付五个与 OCR 引擎互补的通用技能。
- 对 Alibaba 官方 `open-code-review` 与 `open-code-review-delegate` 使用正式版本的精确提交锁；不改写上游原文。
- 插件以校验摘要的 vendor 快照分发七个外部技能；仅本地 `codereview` harness 保留在插件内，明确其入口优先级与授权边界。
- 增加技能来源、离线/在线一致性和上游变化检测。更新文档，区分独立安装与插件内调用。

## Non-Goals

- 不把 OCR 模型判断改成提交强制门禁，不给手动官方技能自动继承插件授权。
- 不修改 FlowGuard、CodeGuard 或宿主已安装缓存。
- 不自动安装/升级 OCR CLI，也不把离线测试当作三端实际加载验收。

## Success Criteria

- 独立技能库可安装、五个技能通过结构与 TRACE 检查；官方两个技能的来源可追溯。
- 插件七个受管技能与本地 harness 无冲突，更新源代码时可检测篡改和 tag 移动。
- 候选提交的审查仍先问用户、只对暂存快照执行；上游技能无法通过插件 hook 绕开授权。
- 插件回归测试、三端清单校验和远端版本链核对通过；未实际测试的宿主保持 UNVERIFIED。
