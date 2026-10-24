# CodeReview (代码变更审查)

> 使用阿里云 OCR 原生命令；插件只做授权编排、路由和报告解释。

**Version**: 0.4.2 · **License**: Apache-2.0 · **Skills**: 8

[简体中文](README.md)

## Positioning

CodeReview is an independent plugin in the Partme Guard family. Its command prefix is ocr. It is installed, versioned and executed independently.

## CLI Commands

| Command | Type |
| :--- | :--- |
| ocr review | 独立入口 |
| ocr scan | 独立入口 |
| ocr delegate preview | 独立入口 |
| ocr delegate rule | 独立入口 |
| ocr rules check | 独立入口 |
| ocr config | 独立入口 |
| ocr llm | 独立入口 |
| ocr session list | 独立入口 |

## Installation

~~~bash
codex plugin marketplace add partme-ai/full-stack-plugins
codex plugin add codereview-plugin@full-stack-plugins
~~~

## Quick Start

~~~bash
ocr version
ocr doctor
ocr status
~~~

## Current Status

使用阿里云 OCR 原生命令；插件只做授权编排、路由和报告解释。

No PASS without real execution evidence. Unimplemented capabilities report DESIGN_ONLY or UNVERIFIED.

## Architecture

See product-docs/CodeReview/ and docs/ for command lifecycle, read-only checks and evidence boundaries.

## Boundaries

- Not merged into a single Partme Guard command.
- Does not replace another Guard's domain decision.
- Does not auto-commit, auto-push or modify user code.

## Verification

~~~bash
python3 -m pytest -q
~~~

## License

Apache-2.0
