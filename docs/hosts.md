# 宿主适配与待授权安装

2026-09-23 核对官方协议和本机 CLI 帮助。以下均未执行安装，实际加载状态为 **UNVERIFIED**。
源路径以下记为 `<插件目录>`；正式聚合市场为 `partme-ai/full-stack-plugins`，插件 ID 为 `codereview-plugin`。市场登记与实际宿主加载是不同证据。

| 项目 | Codex | ZCode | Kimi |
| --- | --- | --- | --- |
| 清单 | .codex-plugin/plugin.json | .zcode-plugin/plugin.json | kimi.plugin.json |
| Hooks | 默认 hooks/hooks.json | 默认 hooks/hooks.json | manifest hooks 数组 |
| 插件根 | PLUGIN_ROOT / CLAUDE_PLUGIN_ROOT | ZCODE_PLUGIN_ROOT / CLAUDE_PLUGIN_ROOT | KIMI_PLUGIN_ROOT；命令 cwd 是插件根 |
| 身份 | session_id | session_id / sessionId | session_id |
| Shell 输入 | command 或 cmd；workdir 覆盖 cwd | command / toolInput 兼容 | tool_input.command |
| 调用关联 | tool_use_id | tool_use_id / toolUseId | tool_call_id 或 tool_use_id |
| 提交前暂停 | exit 2 + stderr | exit 2 + stderr | exit 2 + stderr |

不使用宿主 permissionDecision=ask 表达三选一。Hook 暂停后由技能提问，Hook 本身不读取终端回答、不运行模型。
默认使用 OCR Delegation：Hook 将宿主 payload 中可用的 `model` 纳入披露范围，`ocr delegate preview/rule` 只负责文件与规则解析，语义审查由当前宿主智能体在 Hook 外完成。切换到 OCR-managed 属于授权范围变化，必须重新询问。
会话开始只输出能力上下文；UserPromptSubmit 不猜测授权；Stop 只输出新报告摘要、不阻塞。宿主可能不展示 Stop stdout，智能体应以 result 为展示事实源。
PostToolUse 仅在有匹配调用 ID、明确整数 exit_code=0、实际 HEAD/父提交/候选树匹配时关闭。未知结果结构、异步启动但未完成等情况保持任务，智能体核实后可显式 post-commit。
Hook 超时/异常按可选插件降级为 UNVERIFIED，不宣称阻断所有提交。缺少稳定身份时不共享默认授权；需显式手动单次会话。

## Codex

本机 `codex plugin add --help` 表明通过已配置市场安装，不支持把源码路径当插件 selector。市场入口已发布，可在获得安装授权后使用 `codex plugin marketplace add partme-ai/full-stack-plugins` 与 `codex plugin add codereview-plugin@full-stack-plugins`；这会修改用户宿主配置与缓存，当前未执行。
安装后新建会话，核实插件技能和 Hooks 的用户信任状态；安装不等于信任。卸载使用 `codex plugin remove <实际插件@市场>`。
[官方 Hooks](https://developers.openai.com/codex/hooks) 是协议依据，不以其他客户端 Hook 行为代替 Codex 实测。

## ZCode

在插件页面“创建 → 添加插件市场”选择经批准的本地市场目录/清单，校验后在该市场分组安装。
市场条目已经发布，卸载/禁用通过“管理已安装”，新会话重新确认 Hook 配置与八个技能的发现状态。
[官方插件说明](https://zcode.z.ai/cn/docs/plugin)、[官方 Hooks](https://zcode.z.ai/en/docs/hooks)。

## Kimi

以下是 Kimi 会话内 Slash Commands，不是 shell 的 `kimi plugin` 子命令：

```text
/plugins install <插件目录的绝对路径>
/plugins info codereview-plugin
/reload
```

宿主复制到 managed 目录，源目录改动不会自动更新，需重装。
禁用 `/plugins disable codereview-plugin`；卸载 `/plugins remove codereview-plugin`，按宿主确认流程执行；managed 副本可能保留。
[官方插件说明](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/plugins)、[官方 Hooks](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/hooks.html)。

## 每端真实验收清单

记录宿主版本、插件安装版本、session_id 来源；在无敏感信息临时 Git 仓库验证：八个技能发现、官方技能与 harness 的触发路由、SessionStart 不提问、一次暂停、用户未回答不重复、once、session、mute、跨会话重置、提交失败重试、成功后新任务、撤销、工作目录覆盖、三插件共存。
先验证拒绝路径（零模型请求）；模型路径需单独确认实际端点及允许发送的临时文件。不把 fixture 事件通过记为安装验收通过。
