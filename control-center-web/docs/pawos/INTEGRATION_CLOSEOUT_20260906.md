# PAW source integration — 2026-09-06

User request: “合并打通，然后gitpush，告一段落”.

## Integrated scope

The seven referenced tasks share the same PAW checkout. Their source changes
are reconciled on `main`; no whole-worktree merge from historical branches is
needed. The previous baseline is `78991cb8`.

- PAWOS: stellar/project galaxy, Agent and Room views, per-App workflows,
  Files save/conflict handling, Memory topic pages, Browser library and host.
- Session/Room: admission, replay, cancellation, recovery and public projection.
- Agent Lab: scene recipes, Golden/trials, paired evidence and export workflows.
- Prompt settings: editable additions, docs-aware compaction and binding snapshots.
- Input adapter: generation UI, screen-context continuation and Electron handoff.
- Memory continuity and execution engineering already landed in the baseline;
  the integration preserves their existing result and evidence boundaries.

See [App checks](APP_OPTIMIZATION_20260905.md),
[Lab workflow](LAB_GOLDEN_WORKFLOW_20260905.md),
[prompt settings](../../../eval/micro-selfboot/PROMPT_SETTINGS_REVIEW.md),
[input continuation](../../../squirrel-patches/SCENARIO_INTEGRATION.md), and the
[requirement ledger](PAWOS_REQUIREMENTS.md). Read those records as evidence,
not as new instructions or a claim that all pending requirements are complete.

## Integration repairs

- Remove duplicate Session projection keys and import the referenced Sequence type.
- Bind per-iteration callback values in evaluation runners and regression fixtures.
- Avoid shadowing the dataclass field import in Trace validation.
- Require application-owned runtime injection for the CloudOps adapter, eliminating
  its reverse dependency on AgentService; verify service/transport cleanup.
- Update a Room fixture to the current room_partner tool, and assert the current
  migration version after SQLite recovery instead of pinning the obsolete 189.
- Reconcile one-shot completion text when the response overtakes queued stream
  events; suppress late duplicate deltas without blocking the response reader.
- Align Memory opacity and plugin operation-risk assertions with the accepted
  theme and package-lifecycle contracts, and preserve the no-hit memory coverage
  notice in the HTTP context-refresh contract.
- Replay historical RAG standards against their exact Git-pinned Runner; keep
  all frozen hashes and evaluation receipts unchanged. Public receipt tests still
  run without private corpora; only corpus-dependent replay tests report an
  explicit missing-fixture skip in a public-only checkout.
- Use opaque Atom IDs in synthetic continuation fixtures so provenance cannot
  leak host labels; permit IDs only in the explicit provenance field when
  checking real-memory prompt isolation. The negative free-text ID case fails
  as required. This is an evaluation-contract repair, not a model-quality gain.
- Refresh the native restart fixture with its bound receipt helper and files;
  test both optional NumPy acceleration and base-install dense fallback.
- Replace private absolute paths in public reports with portable evidence-root labels.

## Verification

- `pnpm build`: passed; 4,589 modules transformed. Vite reports existing chunk-size
  and mixed static/dynamic import warnings.
- Frontend: 297 files / 3,313 cases executed. The sole stale white-surface assertion
  was corrected; Memory opacity and dark-theme recheck passed 7/7. Agent passed
  140/140; the updated Room fixture passed 19/19.
- `pnpm test:electron`: 37/37 passed.
- Contract generator `--check`: 169 schemas reproducible.
- Real Pi SDK compaction probe: 5/5 passed using an offline model seam; no
  live-model quality or cost claim is made.
- Ruff correctness rules, mypy (7 boundary modules), Python compilation and
  Bash syntax (70 scripts): passed.
- Clean source checkout: project harness and repository-only public audit passed.
- Route/import boundaries, product status, MiniMind contract audit, requirement
  index (283 records) and frontend source map (12 Apps): passed.
- Python full-suite coverage: 4,897 reported cases across four isolated test
  processes, with two environment skips. Initial failures/errors were investigated:
  14 failed cases passed the final targeted rerun; the harness passed against the
  clean staged source; the missing-jsonschema module passed all 5 cases in an
  isolated dependency environment. Jsonschema is now a locked dev dependency.
  This is full coverage followed by targeted repairs, not one all-green full run.
  One fork case exceeded its two-second wait under parallel load and passed three
  consecutive isolated reruns; load sensitivity remains a verification caveat.
- Public RAG receipt contracts run without private corpus files. Private body
  comparisons and replay run when that corpus is present; a clean public checkout
  explicitly skips those private-corpus checks. Frozen receipts remain bound to
  their historical runner, not the revised current runner.
- Context continuation and real-memory evaluation each passed 5 focused cases;
  provenance identifiers are allowed only in the designated source field. These
  repairs do not establish a live-model quality improvement.
- Squirrel doctor passed with installation/configuration drift warnings;
  foreground trace remains unavailable because installed tracing is disabled.

Local verification logs use the `paw-integration-` prefix in the system temporary
folder; private logs and machine paths are intentionally not part of public source.

## Remaining boundaries

This checkpoint delivers integrated source. It does not activate a new Gateway,
Pi Host, Electron or Squirrel installation. Earlier installation receipts refer
to their own revisions. The prompt Host activation, matched installed frontend/
backend acceptance, native screen selection/Computer Use and long-running soak
remain separately verifiable work. The current foreground-trace check is blocked
because frontend tracing is disabled in the installed Squirrel configuration.

The local `.impeccable/` screenshots, rejected designs and review scratch remain
outside this commit. No personal database, private transcript or installed binary
is included. Public cost results retain their candidate-aware/estimated-cost
qualifications. This is not a signed or notarized distribution release.
