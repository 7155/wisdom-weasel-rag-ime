# PAWOS Authority (tracked for GitHub / cloud models)

Root `/docs/` is gitignored. These copies live in the frontend tree so a model
that can only read GitHub still has the complete requirement set.

| Document | Role |
| --- | --- |
| [PAWOS_REQUIREMENTS.md](PAWOS_REQUIREMENTS.md) | Append-only accepted requirements `UR-001`–`UR-152`, source evidence, corrections. `current` means controlling semantics, not implementation completion. |
| [PAWOS_REQUIREMENT_STATUS.md](PAWOS_REQUIREMENT_STATUS.md) | Per-requirement assessment, independent run/requirement verdicts, E1–E6 evidence receipts, and source-hash freshness. |
| [PAWOS_SHOWCASE.md](PAWOS_SHOWCASE.md) | Current final-verification, Demo, capture, evidence-boundary, and closeout record. |
| [PAWOS_FRONTEND_HANDOFF.md](PAWOS_FRONTEND_HANDOFF.md) | Historical frontend rewrite receipts, Agent/Room `AUI-*`/`RUI-*`, open boundaries. |
| [../../PAWOS_FRONTEND_CLOUD_MODEL_BRIEF.md](../../PAWOS_FRONTEND_CLOUD_MODEL_BRIEF.md) | Current `PF-CM-*` ledger, eleven-App design spec, completion gate. |
| [../../PAWOS_FRONTEND_CONTINUATION_HANDOFF.md](../../PAWOS_FRONTEND_CONTINUATION_HANDOFF.md) | 2026-08-24 checkpoint: what landed on `main`, what remains. |
| [../handoffs/](../handoffs/) | Function inventory, per-App function handoff, privacy-safe fixtures. |

When the brief and this ledger appear to conflict, use the newest explicit user
correction and report the conflict. Do not treat a handoff as proof of install
or foreground acceptance. Do not infer requirement completion from Markdown
checkboxes, diffs, test names, or prose; validate the explicit status index with
`python3 scripts/check_pawos_requirement_status.py`.
