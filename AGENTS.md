# CodeReview 插件维护约束

- `skills.lock.json` 的两个外部来源分别是 `full-stack-skills/codereview-skills` 与 `alibaba/open-code-review`。受管的七个 `skills/*` 目录不得在插件仓直接修改；先在来源仓发布不可变版本，再用 `python3 scripts/vendor/skill_vendor.py update` 更新 lock 和发布快照。
- 插件本地 `skills/codereview` 是提交前授权、暂存快照、报告状态和用户处置的 harness，显式登记在 `plugin-local-skills.json`，绝不放进受管锁。Hook、CLI、宿主适配和证据协议也只在插件仓维护。
- 提交前必须运行 `python3 scripts/vendor/skill_vendor.py check --offline`、在线 `check`、`python3 scripts/validate_local.py` 和受影响测试。不要把官方技能的手动工作区审查当成本插件候选提交审查。
- 已发布 tag 不得移动；任何市场可见的插件更新需要新版本、正式 Release、市场清单同步。真实 OCR 模型调用和 Codex/ZCode/Kimi 运行验收不得由离线测试代替。
