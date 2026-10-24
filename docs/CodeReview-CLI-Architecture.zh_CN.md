# CodeReview CLI 架构设计

## 1. 定位

CodeReview（代码变更审查）是独立 CLI，不依赖统一 guard 调度器。插件只负责宿主集成、Hook 和技能路由。

## 2. 命令分层

生命周期：install/uninstall/upgrade/version/doctor/status/completion。
项目事实：discover/init/check/report。
专业命令：ocr review,ocr scan,ocr delegate preview,ocr delegate rule,ocr rules check,ocr config,ocr llm providers,ocr llm test,ocr session list,ocr --version。

## 3. 状态与证据

项目状态写入 .guard/evidence/ocr/；配置由各工具管理。FlowGuard 只读证据，不替其他工具执行。

## 4. 安全

install 不写项目，init 不写宿主，hooks install 不静默执行。所有写操作支持 --dry-run/--yes。

## 5. 当前成熟度

外部 OCR CLI；插件只做宿主集成与技能编排
