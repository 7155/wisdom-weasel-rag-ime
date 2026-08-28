# PAWOS 用户需求账本 · UR-181

> 导航：[UR-151–UR-180](PAWOS_REQUIREMENTS_151_180.md) · [总索引](../PAWOS_REQUIREMENTS.md) · 下一份：[UR-182](PAWOS_REQUIREMENTS_182_182.md)
>
> `current` 只表示当前控制语义，不表示实现完成。实施状态与证据见
> [PAWOS_REQUIREMENT_STATUS.md](../PAWOS_REQUIREMENT_STATUS.md)。稳定编号、来源、修正关系和原话不得因拆卷而改写或丢失。

### UR-181 — 大型需求账本可无损拆卷，且 Codex / Pi 文档技能必须共同维护导航

- **状态 / 优先级：** `current / P0 document workflow`
- **真实需求：** 当需求账本过大时，不再强制塞进一个 Markdown。允许按稳定
  ID 范围或明确产品域拆成多个需求文件；原来的权威路径保留为总索引，列出
  完整文件集合和每份覆盖范围。
- **必须保留：** 稳定需求 ID、当前控制语义、用户原话、来源、修正关系、
  覆盖审计和独立实施状态。每份文档顶部与末尾都要明确上一份、总索引、
  下一份或“继续读 / 继续改”的精确文件，保证从任一文件进入都能发现全套。
- **技能同步：** 写需求文档的 Skill 必须支持这种拆卷规则；本机 Codex 的
  `organize-work-documents` 与项目 Pi 实际加载的同名 Skill 都要同步，不能只改
  一份说明。
- **禁止：** 以拆分为由概括、删除、重新编号或丢失原话；保留一个没有导航
  的孤立分卷；让 Agent 依赖仓库全量搜索猜测下一份文档。
- **用户可见验收：** 总索引直接列出所有卷；逐卷阅读能连续走到逐字证据、
  产品契约和状态；结构检查证明每个 UR 恰好出现一次，两个 Skill 均通过校验。
- **原话依据：** “你分文件不就好了，这个需求文档”；“那个High的技能，
  就是写需求文档的那个技能也更新一下，就是嗯可以进行拆分。但是就是得知道
  是哪些需求文件，或者文件末尾写就是继续读改读那个文件”；“项目的pi技能
  也得改呀”。来源：当前任务，2026-08-28。

## 继续阅读 / 编辑

- 下一份：[UR-182](PAWOS_REQUIREMENTS_182_182.md)
- 实施状态：[PAWOS_REQUIREMENT_STATUS.md](../PAWOS_REQUIREMENT_STATUS.md)
- 总入口：[PAWOS_REQUIREMENTS.md](../PAWOS_REQUIREMENTS.md)
