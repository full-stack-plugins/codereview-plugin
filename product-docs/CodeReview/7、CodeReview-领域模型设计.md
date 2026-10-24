# CodeReview 领域模型设计

> **文档说明**：定义 CodeReview 的核心对象与状态。
>
> **版本**：V1.0.0
> **最后更新**：2026-10-24

## 1. 核心对象

| 对象 | 说明 |
| :--- | :--- |
| Project | 被检查的仓库或目录 |
| Run | 一次命令执行 |
| Finding | 一条可定位的问题或风险 |
| Evidence | 运行产物、日志、报告或状态快照 |
| Decision | allow / deny / unverified / error |

## 2. 状态流转

~~~text
idle → discover → check → report
                ↘ unverified
                ↘ error
~~~

## 3. 证据规则

- 每个结论必须能回读到真实执行。
- 没有执行证据时不能产生 allow。
- report 只读，不重新执行 check。

## 4. 领域边界

使用阿里云 OCR 原生命令；插件只做授权编排、路由和报告解释

---

**文档状态**：✅ 待评审
