# CodeReview（代码变更审查）

> 使用阿里云 OCR 原生命令；插件只做授权编排、路由和报告解释。

**版本**：0.4.2 · **许可证**：Apache-2.0 · **技能**：8 个

[English](README.en.md)

## 项目定位

CodeReview 是 Partme Guard 研发防护体系中的独立插件，命令前缀为 ocr。它不依赖统一总命令，可独立安装、独立发版、独立执行。

## CLI 命令

| 命令 | 类型 |
| :--- | :--- |
| ocr review | 独立入口 |
| ocr scan | 独立入口 |
| ocr delegate preview | 独立入口 |
| ocr delegate rule | 独立入口 |
| ocr rules check | 独立入口 |
| ocr config | 独立入口 |
| ocr llm | 独立入口 |
| ocr session list | 独立入口 |

## 安装

~~~bash
codex plugin marketplace add partme-ai/full-stack-plugins
codex plugin add codereview-plugin@full-stack-plugins
~~~

## 快速开始

~~~bash
ocr version
ocr doctor
ocr status
~~~

## 当前状态

使用阿里云 OCR 原生命令；插件只做授权编排、路由和报告解释。

没有真实执行证据时，不报告 PASS；未实现能力报告 DESIGN_ONLY 或 UNVERIFIED。

## 架构

命令入口、生命周期、只读检查和证据边界见 product-docs/CodeReview/ 与 docs/。

## 边界

- 不合并为 Partme Guard 总命令。
- 不替代其他 Guard 的专业判断。
- 不自动提交、推送或修改用户代码。

## 验证

~~~bash
python3 -m pytest -q
~~~

## 许可证

Apache-2.0
