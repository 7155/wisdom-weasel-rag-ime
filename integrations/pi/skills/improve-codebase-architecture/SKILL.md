---
name: improve-codebase-architecture
description: Inspect real codebase friction and produce a small, evidence-backed architecture improvement shortlist before any refactor. Use when the user explicitly asks to improve architecture, reduce structural complexity, or find high-value refactoring candidates.
when:
  - 用户明确要求体检代码架构、寻找重构候选或降低结构复杂度
does: 从真实热点、所有权和依赖证据中形成少量候选，并等待用户选定。
input: 目标仓库、当前任务边界、近期改动、架构文档和可运行验证。
output: 一至三个候选、证据、收益、风险、删除测试和推荐顺序。
notFor:
  - 已定位的单点缺陷修复、纯格式整理或为了行数而拆文件
  - 未经选择直接进行大范围重构
---

# Improve Codebase Architecture

## Workflow

1. Read the repository guide, domain glossary, architecture decisions, current
   plan, and recent changes before proposing structure.
2. Inspect real friction: mixed lifecycle ownership, repeated branching,
   duplicated contracts, unstable dependencies, hard-to-test state, and files
   that change for unrelated reasons. File size alone is not evidence.
3. Trace each candidate through its caller, state owner, side effects, tests,
   and downstream consumer.
4. Keep only one to three candidates with concrete evidence and a reversible
   boundary. Prefer deletion, a thinner entry point, or composition over a new
   abstraction.
5. For each candidate, state:
   - symptom and source locations;
   - current owner and desired owner;
   - smallest coherent change;
   - compatibility, migration, and rollback risk;
   - the deletion test: what becomes unnecessary afterward;
   - verification that would prove the change.
6. Recommend an order, but do not implement until the user selects a candidate.
   If the choice depends on product tradeoffs, load `grill-me` and resolve one
   decision at a time.

## Exit Contract

Return the shortlist and stop at `awaiting_selection`, `no_high-value_candidate`,
or `blocked_by_missing_evidence`.

## Boundaries

Do not refactor to satisfy a line-count target, invent a second runtime path,
silently change public contracts, open managed execution, or claim architectural
improvement without a focused diff and fresh verification. Kernel lifecycle and
native permission rules remain authoritative.
