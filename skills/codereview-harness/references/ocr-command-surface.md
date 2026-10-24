# OCR 命令面

只使用已安装 ocr 的真实子命令；参数以 ocr <command> --help 为准。

- ocr review --audience agent --background <context>
- ocr review --from <ref> --to <ref>
- ocr review --commit <hash>
- ocr review --preview
- ocr review --resume <id>
- ocr scan --path <path>
- ocr scan --resume <id>
- ocr delegate preview --format json
- ocr delegate rule --format json <path...>
- ocr rules check <path>
- ocr config provider
- ocr config set llm.<key> <value>
- ocr llm providers
- ocr llm test
- ocr session list

不发明 ocr install、ocr doctor、ocr status 或 codereview check；不把 ocr scan 说成提交审查；不把空输出当 PASS。
