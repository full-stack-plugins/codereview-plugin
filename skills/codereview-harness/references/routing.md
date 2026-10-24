# CodeReview 技能路由

| 场景 | 技能 | 真实命令边界 |
|---|---|---|
| 当前暂存提交的授权审查 | codereview-harness | 只调用插件 scripts/codereview.py；不直接跑裸 ocr review |
| 工作区、分支、单提交审查 | open-code-review | ocr review --audience agent ... |
| 整个目录或无 Git diff 审计 | codereview-scan | ocr scan --path <path> |
| 宿主模型审查，OCR 只做选文件和规则 | open-code-review-delegate | ocr delegate preview / ocr delegate rule |
| 规则制定与命中验证 | codereview-rules | ocr rules check <path> |
| 发现项核实 | codereview-finding-triage | 只读报告与证据 |
| 修复后复审 | codereview-fix-verify | 重新 prepare/review，不复用旧报告 |

## 不可交换的边界

- 提交授权只属于 codereview-harness。
- ocr scan 不冒充提交审查。
- Delegation 不调用 OCR LLM，也不外发源码。
- ocr review 空输出不代表 PASS。
- 不新增 codereview install/check 等自有命令。
