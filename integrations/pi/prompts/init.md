---
description: 通过项目上下文 Skill 创建或补全根级 AGENTS.md
---
先调用 `skill_load`，`name=bootstrap-project-context`，再严格按该 Skill
初始化当前 Session 绑定的项目。`/init` 是显式审查入口；它可以在保留原意的
前提下补全已有根级 `AGENTS.md`，但不得把动态 WorkItem、Session 或完成状态
写成 Markdown 事实。
