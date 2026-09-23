# 验收记录：consent-based-review（v0.1.0 历史基线）

日期：2026-09-23。OpenSpec schema：spec-driven；授权行为事实源为 `openspec/changes/consent-based-review/`。下述 111 项测试和 0.1.0 清单属于首版历史基线，**不是当前版本的执行证据**；真实宿主/模型验收仍未完成。

## 已实际执行

环境：macOS，Python 3.13.5，Git 2.48.1，OpenSpec 1.13.1。

| 命令 | 实际结果 |
| --- | --- |
| `/opt/anaconda3/bin/python3 -m pytest -q` | **111 passed** |
| `python3 scripts/validate_local.py` | Local structure valid: 0.1.0；host runtime UNVERIFIED |
| plugin-creator `scripts/validate_plugin.py .` | Plugin validation passed |
| skill-creator `scripts/quick_validate.py skills/codereview` | Skill is valid |
| `python3 -m compileall -q codereview_core scripts hooks` | 退出码 0 |
| `openspec validate consent-based-review --strict` | Change is valid |

系统技能校验器来自本机 `/Users/wandl/.codex/skills/.system/`。CI 采用仓库自带结构校验，不依赖该机器路径。
当时 CI 尚未创建/推送；此处保留当时的本地证据边界，不代表当前发布状态。
测试中的 OCR 是真实子进程夹具，不是实际 OCR 服务调用；测试 Git 提交只发生在 pytest 临时仓库。

## 规格逐项映射

| 规格 requirement | 实现位置 | 可复现的测试证据 |
| --- | --- | --- |
| review-consent：提交前的三态选择 | consent.prepare/decide | test_consent；test_cli_process_all_choices |
| 会话静默与手动恢复 | Runtime.prepare(manual=True)、reset | test_manual_after_mute_restores_no_automatic_reminders；test_cli_mute_and_new_session |
| 授权范围与会话隔离 | scope digest、Store 会话散列 | test_consent 六类 scope 变化；test_missing_session_degrades_without_shared_default |
| 逻辑任务内重试与撤销 | run token/epoch/任务锁、cancel | test_cancel_stops_running_review_and_late_write；test_abandoned_run_is_explicitly_retried；test_post_failure_keeps_authorization |
| 授权与其他操作分离 | 内核无编辑/提交入口；编排技能约束 | test_report_instructions_are_data_not_modifications_or_consent；**智能体实际对话层仍待验证** |
| commit-review：精确提交内容 | Git 对象读取、隔离合成提交 | test_partial_index_snapshot_and_original_repository_unchanged；test_first_commit_and_newline_name；命令形式参数表 |
| 报告与证据失效 | 指纹 + scope + 提交前重算 | test_changed_index_cannot_reuse_report_or_disposition；test_fingerprint_changes_on_index_and_baseline_not_worktree |
| 审查结果不等于门禁裁决 | proceed/skip/evidence_status | test_consumer_requires_current_evidence_but_never_grants_acceptance；test_report_instructions_are_data_not_modifications_or_consent |
| OCR 双执行模式 | OCR.capabilities/scope/delegate/review_managed、Runtime.complete_delegated | test_capabilities_do_not_require_llm_configuration；test_delegated_scope_discloses_host_without_ocr_llm_config；test_managed_review_reads_private_output_file_not_stdout |
| 引擎异常不得伪装成功 | engine.normalize、能力探测、preview、逐文件回执、进程限额 | test_engine 状态/畸形输出表；test_missing_required_capabilities_and_binary_never_review；test_all_filtered_preview_never_claims_success_or_calls_model；test_delegated_runtime_requires_complete_coverage_and_cleans_snapshot |
| 审查执行范围和隔离 | Candidate、Snapshot.materialize/cleanup、run_process | test_symlink_submodule_conflict_and_size_are_explicit；test_size_and_path_limits；test_case_colliding_tree_is_rejected；test_candidate_change_invalidates_delegate_plan_and_cleans_snapshot；超时/取消清理 |
| host-integration：Hooks 与智能体职责分离 | hosts.handle、独立 CLI | test_hooks_pause_only_commit_then_silence_after_mute；test_host_context_and_stop_summary_are_not_authorization_questions |
| 提交事件识别与幂等 | classify、pending_call、post_commit | test_commit_command_normalization；test_post_hook_requires_matching_call_and_actual_success |
| 多宿主适配与能力报告 | 三端清单、hosts、docs/hosts | test_manifests_have_separate_host_loading_contracts；test_actual_hook_process_pauses_on_stderr（三端参数化）；**真实加载待验收** |
| 插件之间不依赖回调顺序 | 独立证据 + 参考消费者 | test_consumer_requires_current_evidence_but_never_grants_acceptance；docs/protocol；未修改另外两个插件 |
| 状态可靠性与隐私 | Store、cleanup、recover | test_store 多进程事务；test_multiprocess_single_flight；test_cleanup_revokes_only_current_session_reports；test_explicit_recovery_quarantines_only_session_state |

## 红—绿回归中暴露并修复的问题

- Hook 对普通管道/环境变量误拦截；缩小到疑似提交，不承诺解析动态 Shell。
- 静默后无法手动单次审查；新增不改变会话偏好的 manual 路径。
- 在源码目录中创建状态后才拒绝；提前校验且保持源码不变。
- Git `core.fsmonitor` 可在只读索引时执行项目配置程序；显式禁用，并使用真实哨兵脚本验证未执行。
- 大小写/Unicode 路径可能在宿主文件系统碰撞；拒绝碰撞，不覆盖候选内容。
- 报告失败被当作缓存结果、端点切换时潜在错误授权、工作目录覆盖丢失；分别加入回归并修复。
- 全部 preview 文件被过滤仍可能显示 success；现在不发模型请求，明确 skipped。
- 固定 v1.6.5 与 stdout JSON 会把新版 OCR 正式接口拒之门外；改为能力探测、Delegation 默认和 managed 私有 `--output`。
- 委托计划若候选内容变化会遗留私有快照；现在状态失效同时按受管标记清理，旧回填被拒绝。

## 尚未完成：3 / 26 个任务

1. **5.4 技能对话层验收（部分完成）**：技能内容、本地技能声明、结构校验、行为用例已交付，内核负例已验证；尚未在独立智能体/真实宿主中执行对话用例，不能以文本检查代替行为验收。
2. **7.1 真实 OCR**：本机 OCR v1.6.5 不具备新版能力；需要用户另行授权升级，并确认实际模型端点、模型与无敏感临时代码外发范围；未调用真实模型、未改变用户 OCR 配置。
3. **7.2 三端安装加载**：需要安装授权和对应宿主，逐端核对运行版本、技能发现、Hook 事件及三种选择；安装后联同 5.4 验收。

其余 23 项有本地实现与验证证据。源码提交、版本 tag、GitHub Release、市场登记和实际宿主运行分别需要独立核对；本记录不能代替真实 OCR 或三端安装验收。FlowGuard/CodeGuard 的原有工作不在本轮修改范围。

## v0.2.0 技能整合的发布基线

规格事实源为 `openspec/changes/integrate-codereview-skills/`；此变更只约束技能分发与路由，不覆盖上文授权规格。2026-09-23 本地执行：

| 检查 | 结果 |
| --- | --- |
| 独立技能仓 `scripts/lint_skills.py` 与 5 个 `quick_validate.py` | 5/5 通过 |
| 独立技能仓 TRACE 确定性基分 | 4.22–4.42；见仓库 `TRACE_EVALUATION.md`，无真实效果对照 |
| `python3 scripts/vendor/skill_vendor.py check --offline` | 7 个受管技能与锁中摘要一致 |
| `python3 scripts/vendor/skill_vendor.py check` | 两个固定 tag 的 peeled commit 与目录内容一致 |
| `/opt/anaconda3/bin/python3 -m pytest -q` | **114 passed** |
| `python3 scripts/validate_local.py`、插件结构校验 | 均通过；宿主运行 UNVERIFIED |
| `openspec validate integrate-codereview-skills --strict` | Change is valid |

本机 Codex `quick_validate.py` 对 Alibaba 原版两个技能的可选 `compatibility` frontmatter 字段报 schema 不支持；没有为通过本机工具而改写上游受管副本。官方技能的原版一致性由 vendor 哈希验证；实际 Codex 发现/加载仍待新环境验收。

## v0.2.1 `codereview-harness` 命名修正

插件专属技能从 `skills/codereview` 更名为 `skills/codereview-harness`，更新了本地清单、Hook 提示和回归测试。独立技能仓的两个路由引用已在 `v0.1.1` 修正，插件锁随之更新；七个受管技能仍保持来源可追溯。macOS CI 暴露已退出子进程的进程组清理可能返回 `PermissionError`；修正为不覆盖原结果，父进程仍存活时直接终止，并加入回归测试。`/opt/anaconda3/bin/python3 -m pytest -q` 为 **115 passed**；技能 quick_validate、本地结构校验、受管技能离线校验和 OpenSpec strict 校验通过。这些检查不代表已安装宿主包含新名称；tag、Release、市场和 CI 分别核对。

## 2026-09-24 真实引擎与双模式验收（7.1 完成）

环境：macOS，ocr v1.12.9（npm 官方包 bccbc15，与技能锁同一提交；Homebrew bottled 1.12.9 亦可识别），真实端点 Zhipu glm-4.7。外发内容仅 `/tmp` 无敏感信息玩具仓库。

| 环节 | 实际结果 |
| --- | --- |
| `doctor` | `{"version":"1.12.9","action":"ready","delegated":true,"managed":true}` |
| 真实 Delegation 全链路 | prepare→ask_user→decide(once)→review 计划（真实 preview/rule）→宿主逐文件审查 3 findings→complete-delegated（success）→真实提交→post-commit `closed:true` |
| 真实 OCR-managed 全链路 | prepare(ocr-managed，真实端点披露)→decide(once)→review（真实模型调用）success→真实提交→post-commit `closed:true` |

验收中暴露并修复的真实缺陷（根因类别：夹具仿真 schema 与上游实样漂移）：

1. `review` 请求漏带 `execution_mode` 时范围重推导静默撤销授权并误报 `not_authorized`；现显式报 `execution_mode_mismatch`。
2. 真实 delegate 输出为 `schema_version` + 整数 `group_id`，原校验只认想象的 `version` + 字符串；现兼容两种并以真实样例为契约（`tests/fixtures/real_v1129_*.json`）。
3. 遥测开启时引擎 OTEL JSON 污染 stdout（解析失败的隐藏根因）；现两种模式统一拒绝遥测开启配置，拒绝发生在任何引擎子进程之前。
4. 真实 `result.json` 的 `status` 为 `complete`，`normalize` 原只认想象枚举；已兼容并以真实样例钉契约。
5. 版本识别兼容 Homebrew 分发的无 `v` 前缀版本串。

`python3 -m pytest -q`：**120 passed**（新增 5 项真实契约/回归测试）。宿主验收续（2026-09-24）：**Codex** 0.153.4 经市场安装 0.2.1 后 `codex exec` 实测 `hook: PreToolUse Blocked`，提交被拦截返回 ask_user，宿主模型正确纳入披露范围；注意 Codex 的 hook 信任边界——安装/启用后钩子在用户信任审查前静默跳过（首次实测即因此未拦截），自动化可用官方 `--dangerously-bypass-hook-trust`。**ZCode** 本会话两次真实暂停疑似提交命令、重复暂停 `notify:false` 不重复发问（安装副本 0.1.0，待随市场升级）。**Kimi** 本机无 Kimi Code CLI（uv 软链断裂，npm `kimi-code` 系第三方代理包未安装），未验收。两个 OpenSpec 变更已按 2/3 宿主真实证据归档为 `2026-09-24-*`；Kimi 与 Codex 信任审查属已知缺口，不以离线测试替代。

## 剩余风险

合作式 Harness 不是恶意进程防护：同用户可修改状态，授权事件引用不是签名；无操作系统沙箱，Git 别名/脚本绕过、配置读取及提交前竞态仍需明确接受。Windows 原生不支持。模型可能漏报，limited 覆盖不等于完整；用户继续不等于检查通过。外部配置/规则不支持时须解释并允许跳过，不静默扩大授权。
