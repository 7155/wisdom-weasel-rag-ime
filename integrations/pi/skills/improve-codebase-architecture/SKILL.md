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

## Evidence Standard

Architecture work earns its cost only when it removes repeated decisions,
clarifies lifecycle ownership, or makes a meaningful boundary independently
testable. File size, naming taste, and abstract "cleanliness" are not evidence.

## Workflow

1. Read the repository guide, domain glossary, architecture decisions, current
   plan, and recent changes before proposing structure.
2. Inspect real friction: mixed lifecycle ownership, repeated branching,
   duplicated contracts, unstable dependencies, hard-to-test state, and files
   that change for unrelated reasons. File size alone is not evidence.
3. Trace each candidate through its interface, callers, state owner, side
   effects, tests, and downstream consumer. Ask:
   - **depth**: does the module hide meaningful complexity behind a small,
     stable interface?
   - **locality**: can a maintainer understand and change one behavior without
     opening unrelated lifecycle owners?
   - **seam**: is there a natural boundary for testing, substitution, or
     migration, rather than an artificial wrapper?
   - **adapter**: is compatibility translated once at the edge, or leaking
     branches through the core?
   - **leverage**: will one change delete repeated decisions across callers?
4. Keep only one to three candidates with concrete evidence and a reversible
   boundary. Prefer deletion, a thinner entry point, a deeper owner module, or
   composition over a new abstraction.
5. For each candidate, state:
   - symptom and source locations;
   - current owner and desired owner;
   - smallest coherent change;
   - compatibility, migration, and rollback risk;
   - the **deletion test**: which branches, adapters, state copies, or files become
     unnecessary afterward;
   - verification that would prove the change.
6. Recommend an order, but do not implement until the user selects a candidate.
   If the choice depends on a product tradeoff, use `grill-with-docs` only when
   the user also wants a durable glossary, ADR, or decision record; otherwise
   follow `grill-me`. Load only the selected exact Skill and resolve one
   decision at a time.

## Candidate Card

```text
Symptom and locations:
Current owner -> desired owner:
Callers and downstream consumers:
Smallest coherent change:
What becomes deletable:
Compatibility and migration:
Rollback:
Fresh verification:
Expected maintenance gain:
```

Reject a candidate when it only moves lines, creates a wrapper without hiding
complexity, duplicates a runtime path, or requires broad migration before any
behavior can be verified.

## Exit Contract

Return the shortlist and stop at `awaiting_selection`, `no_high-value_candidate`,
or `blocked_by_missing_evidence`.

## Self-Check

- Does each candidate follow a real call path and state owner?
- Will the change delete branches, state copies, or repeated translations?
- Is the entry point thinner and the owning module deeper?
- Can the change be verified and rolled back independently?
- Did I keep implementation outside the architecture-selection phase?

## Boundaries

Do not refactor to satisfy a line-count target, invent a second runtime path,
silently change public contracts, open managed execution, or claim architectural
improvement without a focused diff and fresh verification. Kernel lifecycle and
native permission rules remain authoritative.
