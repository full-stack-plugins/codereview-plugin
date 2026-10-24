# CodeReview Command Reference

Status: 外部 OCR CLI；插件只做宿主集成与技能编排

## Commands

install, uninstall, upgrade, version, doctor, status, discover, init, check, report, plus domain commands: ocr review,ocr scan,ocr delegate preview,ocr delegate rule,ocr rules check,ocr config,ocr llm providers,ocr llm test,ocr session list,ocr --version.

Exit codes: 0 PASS, 1 BLOCK, 2 usage/config, 3 UNVERIFIED/DESIGN_ONLY, 4 internal/runtime error.

No PASS without real execution evidence. CodeReview uses Alibaba OCR commands directly.
