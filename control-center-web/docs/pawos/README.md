# PAWOS Authority (tracked for GitHub / cloud models)

Root `/docs/` is gitignored. These copies live in the frontend tree so a model
that can only read GitHub still has the complete requirement set.

| Document | Role |
| --- | --- |
| [PAINTED_GALAXY_CONTINUATION_20260906.md](PAINTED_GALAXY_CONTINUATION_20260906.md) | UR-282: user-directed code-painted spiral, beauty-first composition, progressive labels, source checks and bounded visual review; no App installation. |
| [OS_CAPABILITY_LIFECYCLE_CONTINUATION_20260906.md](OS_CAPABILITY_LIFECYCLE_CONTINUATION_20260906.md) | UR-278–UR-283: own-Session model labels, automatic recovery, in-OS Package authoring/apply, scenario Skills, user-requested visual rollback and both project display modes; source and installed boundaries. |
| [STELLAR_BROWSER_CONTINUATION_20260905.md](STELLAR_BROWSER_CONTINUATION_20260905.md) | UR-267–UR-277: Browser libraries, dark stellar desktop, independent 3D galaxy, photographed surfaces, volume dust, orbit simulation, real docs and centered execution mark; source, visual feedback and installed boundaries. |
| [APP_OPTIMIZATION_20260905.md](APP_OPTIMIZATION_20260905.md) | Current Astra parallel per-App improvements, Agent Lab visualization, causal fixes, source/browser checks and remaining native/real-model acceptance boundaries. |
| [LAB_GOLDEN_WORKFLOW_20260905.md](LAB_GOLDEN_WORKFLOW_20260905.md) | Golden drafting, human review, Judge calibration and frozen experiment implementation and acceptance. |
| [PAWOS_REQUIREMENTS.md](PAWOS_REQUIREMENTS.md) | Canonical index for the forty-four append-only requirement volumes `UR-001`–`UR-283`, exact-source evidence, product contract, and continuation links. `current` means controlling semantics, not implementation completion. |
| [requirements/](requirements/) | Forty-four stable-ID ledger volumes plus separate verbatim evidence and cross-requirement product contract. Every file links to previous, index, and next. |
| [UR-260–UR-264](requirements/PAWOS_REQUIREMENTS_260_264.md) | Current continuation: whole OS light stellar depth, OAuth before metrics, independently visible running partners, Runtime trace recovery, and causal documentation; eight exact user sources with correction and acceptance boundaries. |
| [UR-265–UR-266](requirements/PAWOS_REQUIREMENTS_265_266.md) | Stellar rejection and Memory optimization; [causes, changes and verification](STELLAR_MEMORY_TOPIC_PAGES_20260905.md). |
| [PAWOS_REQUIREMENT_STATUS.md](PAWOS_REQUIREMENT_STATUS.md) | Per-requirement assessment, independent run/requirement verdicts, and E1–E6 evidence receipts. |
| [PAWOS_RELIABILITY_CONTINUATION_20260905.md](PAWOS_RELIABILITY_CONTINUATION_20260905.md) | Current owner-maintained cause, fix, regression and source / Runtime / native evidence record. A source test or a geometry check does not prove installation or full Room recovery. |
| [PAWOS_SHOWCASE.md](PAWOS_SHOWCASE.md) | Current final-verification, Demo, capture, evidence-boundary, and closeout record. |
| [PAWOS_TRACE_EVAL.md](PAWOS_TRACE_EVAL.md) | Common Trace authority, producer timing/privacy, retrieval evidence, deterministic and estimated Eval boundaries, periodic schedules, vertical fixtures, and UI acceptance limits. |
| [PAWOS_ISLAND_SETTINGS_DESIGN.md](PAWOS_ISLAND_SETTINGS_DESIGN.md) | `UR-175` discussion draft: current owners, two island/settings directions, recommendation, non-goals, and open user decisions. |
| [PAWOS_FRONTEND_HISTORY.md](PAWOS_FRONTEND_HISTORY.md) | Historical frontend rewrite receipts, Agent/Room `AUI-*`/`RUI-*`, open boundaries. |
| [../../PAWOS_FRONTEND_CLOUD_MODEL_BRIEF.md](../../PAWOS_FRONTEND_CLOUD_MODEL_BRIEF.md) | Current `PF-CM-*` ledger, eleven-App design spec, completion gate. |
| [../../PAWOS_FRONTEND_CONTINUATION.md](../../PAWOS_FRONTEND_CONTINUATION.md) | 2026-08-24 checkpoint: what landed on `main`, what remains. |
| [../handoffs/](../handoffs/) | Function inventory, per-App function handoff, privacy-safe fixtures. |

When the brief and this ledger appear to conflict, use the newest explicit user
correction and report the conflict. Do not treat a handoff as proof of install
or foreground acceptance. Do not infer requirement completion from Markdown
checkboxes, diffs, test names, or prose; validate the explicit status index with
`python3 scripts/check_pawos_requirement_status.py`. The checker discovers the
indexed split volumes; a document hash is diagnostic metadata, not a product or
Room completion gate.

## 交接与归档边界

本地 Session 完成相关文件整理、检查、提交并把最终提交合并到 `main` 后，
用户再把该 `main` 归档基线交给外部前端模型复核和优化。外部模型从
[CLOUD_MODEL.md](../../CLOUD_MODEL.md) 和本索引进入；它必须以实际合并提交、
新鲜检查和 [PAWOS_REQUIREMENT_STATUS.md](PAWOS_REQUIREMENT_STATUS.md) 为准，
不能把本目录的文字、截图或旧 handoff 当成安装/前台验收证据。
