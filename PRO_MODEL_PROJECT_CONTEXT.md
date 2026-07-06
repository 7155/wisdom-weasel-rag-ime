# Wisdom-Weasel RAG IME - Single-File Context For Pro Model

Generated: 2026-07-05  
Repo path on the user's machine: `/Volumes/undo 4t/git/learnA/wisdom-weasel-rag-ime`  
Public repo URL, when accessible: `https://github.com/7155/wisdom-weasel-rag-ime`  
Current branch: `codex/wisdom-weasel-rag-ime-mvp`  
Purpose: this file is a self-contained handoff for a Pro model or engineer when
GitHub access is unavailable.

## Prompt To The Pro Model

You are reviewing a macOS Chinese input method project. The user is frustrated
because earlier iterations often proved only backend JSON, while the actual
foreground input method still felt unusable. Do not redefine success around
backend tests. Treat real foreground Squirrel/Rime behavior as the product.

Your job is to analyze the project from this single file, then propose or make
concrete fixes in the repository if available. Preserve these hard boundaries:

- Rime/Wanxiang stays the base IME for pinyin, fuzzy pinyin, dictionary
  candidates, paging, and fallback.
- This project adds side candidates from local LLM prediction and local
  RAG/memory.
- Realtime prediction must use a local small model. The high-intelligence
  `x1top` GPT-series lane, currently configured through `x1api.top`-compatible
  env variables, is only for offline memory/RAG/lexicon cleanup.
- The final UX needs visible LLM/RAG/dictionary source distinction, number-key
  selection, correct Backspace/Delete context, and continuous prediction after
  selecting a side candidate.
- Use `Felix3322/Wisdom-Weasel` as the main behavioral reference, especially for
  context history, request/session identity, display candidate lists, feedback,
  and stale-result discard. Do not blindly port Windows TSF code.

## One-Screen Summary

This is a local-first macOS RAG input method prototype inspired by
`Felix3322/Wisdom-Weasel`.

Runtime shape:

```text
macOS Squirrel / Rime
  -> Rime parses pinyin and produces normal dictionary candidates
  -> patched Squirrel captures raw input, preedit, committed context, Rime candidates
  -> Python sidecar merges local model + RAG/memory + Rime fallback
  -> candidate panel displays source-aware candidates
  -> number keys select visible side candidates instead of inserting digits
  -> selection feedback updates local memory/frequency state
```

Current state:

- The repository has a patched Squirrel route and a debug-only native AppKit
  harness.
- The sidecar, local SQLite memory/RAG core, MLX local predictor, source-lane
  merge, feedback recording, and many tests exist.
- Current verification after the latest product-gate/optimizer repair:
  `python3 -W error::ResourceWarning -m unittest discover -s tests` reports
  `Ran 534 tests in 98.077s`, `OK`.
- Earlier runtime repair verified selected input source
  `im.rag-ime.inputmethod.RagIme.Hans`, sidecar `127.0.0.1:8766`, MLX predictor
  `127.0.0.1:8767`, and mixed model/RAG candidates.
- Remaining core problems are product-quality and foreground UX, not only
  missing backend modules.

Most important unfinished item:

```text
real foreground continuous selection
-> true KV/cache fork beyond seeded prompt replay
-> RAG/x1top offline database cleanup
-> source-colored candidate display polish
```

## User Requirements

Preserve these user statements as product requirements:

- "输入依旧没有 LLM 和 RAG 以及记忆" means backend data is not enough; LLM/RAG/memory
  must appear in the actual input method.
- "不是真实" and "预测感觉随机" mean the model lane must be traceable to active
  context, not generic filler.
- "上下文要按照实际输入，因为有删除的情况" means committed context must follow real
  foreground text after Backspace/Delete.
- "预测弹出框后选 123 没用，输入就是 123" means number keys must select live
  candidates, not insert literal digits when a side panel is active.
- "预测只有一个的话还不如 Tab" means one LLM candidate is not enough; the local
  model must produce multiple useful next-word or next-phrase candidates.
- "x1api 不要用来预测" means the `x1top` GPT-series lane, currently wired
  through `x1api.top`-compatible config, is only for offline memory/RAG/lexicon
  optimization.
- "预测是本地的小模型" means realtime inference must remain local.
- "本地模型还能 KV" means the provider path should evolve toward prompt/KV cache
  and native local inference optimization.
- "四川人，模糊音必须可以设置，默认开启" means Sichuan fuzzy pinyin should be
  configurable and enabled by default in Rime bootstrap.
- "预测和 rag 以及词库用三种颜色" means the source lanes must be visually
  distinguishable.

The user's priority repair order:

1. Real foreground Squirrel install verification.
2. Backspace/Delete real context correctness.
3. RAG dedupe and database reorganization.
4. Local model multi-word continuous prediction quality.

## Expected Final Product

The acceptable product should behave like this:

```text
User types normally
  -> Rime/Wanxiang remains stable and immediate
  -> LLM appears as compact prediction candidates
  -> RAG/memory appears only when relevant to the actual current context
  -> dictionary/Rime fallback remains visible and selectable
  -> sources are visually distinct
  -> 1/2/3 selects the visible candidate bound to the current session
  -> selecting a side candidate immediately triggers the next prediction
  -> Backspace/Delete invalidates stale LLM/RAG context
```

Explicitly unacceptable:

- `/rime-suggest` returns JSON but foreground panel never shows it.
- RAG repeats old complaint/debug/input history unrelated to current context.
- LLM returns only one candidate or generic filler such as "下一步", "接下来",
  "根据上述".
- Backspace/Delete leaves deleted text in the model/RAG query.
- Candidate popup flashes too quickly to select.
- Number keys insert `1`, `2`, `3` while a live side candidate is visible.
- x1api or any cloud API is placed in the realtime per-keystroke prediction path.

## Active Implementation Roadmap

The current goal is to implement the attached PR roadmap in order:

1. PR-1 foreground transaction and stale guard hardening.
2. PR-2 real Squirrel foreground soak trace gate.
3. PR-3 commit barrier and continuous prediction chaining.
4. PR-4 MLX `seededPromptReplay` top-k seed replay, while keeping
   `sequenceFork=false` and `kvFork=false`.
5. PR-5 RAG anti-echo and governance layering.
6. PR-6 x1top GPT-series offline cleanup pipeline with dry-run, review, apply,
   and rollback through the `x1api-compatible` config boundary.
7. PR-7 Squirrel product candidate source badges/colors.
8. PR-8 Sichuan mild fuzzy profile check/apply scripts.
9. PR-9 model matrix, reranker, and quality eval.
10. PR-10 localhost-only management UI v1.

Current checkpoint: PR-1 through PR-10 have active implementation work in-tree.
Python sidecar transaction parsing/echo and trace checker transaction
validation are implemented; Squirrel patch text now contains the matching
transaction fields, response validation, stale selection rejection, hash-only
default trace, pending post-commit continuation barrier, and post-commit trace
event names. The frontend/soak trace checkers now only count a post-commit
follow-up request when its `commitTextPreview` matches the side candidate that
was just committed, preventing unrelated blank no-input requests from passing
the continuous-prediction gate. The local MLX predictor now also has a first PR-4
`seeded-prompt-replay` mode for `no_input_prediction`. The PR-5 governance
layer also exposes reviewable local CLI commands for tombstones and anti-echo
inspection instead of hiding everything behind sidecar-only behavior, and the
anti-echo optimizer is now on by default in the sidecar lane with
mode-sensitive exemptions for prefix composition and strong post-commit phrase
reuse. The local core default suggestion path now also performs a conservative
v2 recovery step: if legacy retrieval surfaces a long raw-history sentence but
memory-v2 can provide a compact compiled phrase, the core prefers that v2
phrase candidate. Current PR-5 follow-up also unified governance on both
retrieval paths: repeated-skip suppression and manual tombstones now apply to
legacy suggestions and memory-v2 candidates consistently, and tombstoning a
phrase candidate also tombstones sibling rows from the same source event so the
same text does not bounce back as `raw:event:*`. The recent-commit echo guard
now also covers pinyin composition for raw-history/RAG event hits, while
preserving `phrase-memory`, `curated`, generated memory, and API lexicon entries
so accepted high-frequency phrases are not over-blocked. PR-6 now also has a real
offline cleanup CLI safety gate: `cleanup-preview` is dry-run only, plan files
can be validated before apply, `cleanup-apply` requires explicit `--apply`, and
rollback is exposed as a first-class command. Generated stable memory also now
supports explicit `evidenceEventIds` from the model plus local event-evidence
backfill when the exported bundle contains a strong matching source event.
PR-8 `memory-compile` is dry-run by default as well: it emits a sanitized,
reviewable JSON diff and does not store a cleanup run unless `--save-draft` is
explicitly passed; applying still requires `memory-compile-apply --diff` or a
reviewed stored run.
PR-7 has started: `displayCandidates` now carry compact source badges and color
tokens (`模/查/忆/词/input`), the Squirrel patch traces those fields without
changing selection keys, and the foreground trace checker rejects source visual
mismatches. Candidate quota now prevents LLM/model output from occupying all
side slots when RAG/memory exists: model display is capped at two visible slots,
RAG/memory keeps block slots, and Rime/Wanxiang fallback keeps reserved slots.
The real foreground verifier/soak scripts now default to
`--require-balanced-quota`, with trace output exposing
`latestBalancedCandidatePanel` and `candidateQuotaViolations`.
PR-8 has started: the Sichuan fuzzy-pinyin helper is now split into
JSON check and explicit dry-run/apply scripts with backup, and the default
profile is mild (`z_zh/c_ch/s_sh/en_eng/in_ing` on, `n_l/f_h` off). PR-9 has
started: `model-matrix-eval` is now a real alias for the local model matrix,
reports product metrics for top-3 coverage, echo, duplicates, latency, and
chain readiness, and `rerank-demo` exposes a source-aware Rime/model/RAG/memory
ranking path that preserves Rime fallback. PR-10 has started: `debug-server`
now exposes localhost management APIs for candidate explain, history audit,
memory/lexicon review, cleanup diff apply/rollback, redacted-by-default raw
history, and action audit logging. The final integrated product gate has also
started: `scripts/run_product_readiness_gate.sh` now runs unit tests,
deterministic acceptance, backend `quality-gate`, and, when
`RAG_IME_REQUIRE_MACOS_FRONTEND=1`, the real Squirrel tryout plus soak-report
checker. `quality-gate` now has `--max-old-input-echo-rate`, and
`check_squirrel_soak_report.py` now has `--max-stale-applied`. The memory
optimizer fail-closed path also now treats explicit degraded optimizer results
as lane failures: the sidecar reports `failClosed=true` and returns no RAG
candidates from that degraded optimizer pass. Memory feedback and governance
action writes are best-effort as well, so failed local DB/action writes cannot
block candidate display or `insertText` commit. The realtime RAG lane now also
turns retrieval/database exceptions into `failClosed=true` with a
`rag_exception:*` warning while preserving model predictions and Rime fallback.
The gate now seeds demo and
eval-case fixture memories into its isolated DB before backend quality-gate, and
predictor capability checks are explicit via
`RAG_IME_REQUIRE_PREDICTOR_CAPABILITY=seededPromptReplay` rather than required
on machines without a running local MLX service. The product gate now also
separates backend eval DB from installed frontend runtime DB:
`--db-path` / `RAG_IME_GATE_DB_PATH` remains for backend quality-gate, while
`--frontend-db-path` / `RAG_IME_FRONTEND_DB_PATH` is passed to
`squirrel-tryout-gate` and defaults to
`~/Library/Application Support/RagIme/rag-ime.sqlite`. Latest foreground-gate
evidence: LaunchAgent, sidecar health, local MLX predictor config, Rime
defaults, and Rime build artifacts are healthy. Patched Squirrel now builds
with Xcode 26.6 and is installed at
`/Users/undo/Library/Input Methods/Squirrel.app`; `installed-bundle` passes and
the latest foreground-required gate confirms the installed Squirrel bundle,
Rime config/defaults/build, LaunchAgent, sidecar health, and `/rime-suggest`
probe are good. A command-line preference repair backed up
HIToolbox/inputsource plists but macOS denied direct persistence of
`com.apple.inputsources`; atomic replace and in-place write both returned
`PermissionError: Operation not permitted`. The remaining machine blocker is
macOS user input-source activation.
`im.rime.inputmethod.Squirrel.Hans` is visible, enabled, selectable, and
HIToolbox-enabled, but `thirdPartyEnabled=false`; the current source is
`com.apple.keylayout.ABC`. A 2026-07-06 read-only audit initially reported
`duplicatePathCount=5` from old backup app paths under
`/Users/undo/Desktop/rag-ime-input-method-backups/system/`. Running
`refresh_squirrel_input_source_registration.sh` against the product
`Squirrel.app` / `im.rime.inputmethod.Squirrel` route unregistered those stale
LaunchServices records; the follow-up audit reported `duplicatePathCount=0`
with only `/Users/undo/Library/Input Methods/Squirrel.app` remaining. The
foreground gate still includes concrete duplicate paths plus `cleanupCommands`
in `manualRequired`, and `RAG_IME_QUARANTINE_STALE_SQUIRREL_APPS=1` prints a
concrete `sudo mv` cleanup command if root-owned backup bundles are later
rediscovered. The latest read-only audit still reports
`readiness.state=third-party-missing`, `wouldChangeHitoolbox=false`, and
`wouldChangeThirdParty=true`. True foreground soak still requires the System
Settings Add/select flow for `Squirrel - Simplified`. Cleanup diff apply now
re-validates stored diffs
before writing, and memory optimizer evidence avoids leaking long stable-memory
source sentences when the compiled IME candidate is short.

Latest default product-gate evidence: `scripts/run_product_readiness_gate.sh`
passes with `583 tests OK`, deterministic `scripts/acceptance.py`,
`rag-pass-rate=0.9706`, `rime-sidecar-pass-rate=0.9706`, old-input echo `0.0`,
warm suggestion/Rime cache hits, and no sidecar RAG/model timeouts. Latest
backend product-gate evidence with the installed local MLX runtime:
`RAG_IME_REQUIRE_PREDICTOR_CAPABILITY=seededPromptReplay scripts/run_product_readiness_gate.sh --skip-unit-tests --skip-acceptance`
passes. The script recovers predictor env from
`~/Library/LaunchAgents/com.rag-ime.sidecar.plist`, uses the installed
`RAG_IME_PREDICTOR_TIMEOUT_MS=6500` as the sidecar eval budget, verifies
`seededPromptReplay=true`, and reports `rag-pass-rate=0.9706`,
`rime-sidecar-pass-rate=0.9706`, `rime-sidecar-model-timeout-rate=0.0`, and
`rime-sidecar-rag-timeout-rate=0.0`. The gate now resets its isolated backend
eval DB by default before seeding fixtures and skips the embedded acceptance
subcheck inside `quality-gate` because `scripts/acceptance.py` already runs
before eval fixtures are inserted. The memory optimizer now protects
high-confidence curated top retrieval hits unless governance blocked them, so
exact RAG hits such as `rimeSuggestCache / cacheStats` are no longer hidden by
optimizer reranking. The display merge also reserves more side slots for
RAG/memory when the model is active: with 5 side slots, the model gets at most
two early rows before protected RAG/memory rows.

## Source Repository Structure

Important root files:

- `README.md`: public overview and start points.
- `AGENTS.md`: short agent guide for public/code-model review.
- `PRO_MODEL_PROJECT_CONTEXT.md`: this single-file handoff.
- `pyproject.toml`: minimal Python project metadata.
- `.gitignore`: ignores `.env*`, SQLite databases, model files, logs, build
  outputs, archives, and local input history.

Active docs:

- `docs/project-status.md`: authoritative current project status, user
  requirements, acceptance criteria, and remaining work.
- `docs/design-decisions.md`: stable architecture decisions and boundaries.
- `docs/runtime-and-debug.md`: local run, install, doctor, and evaluation
  commands.
- `docs/eval/*.jsonl`: small regression/evaluation cases.
- `docs/archive/`: old process logs and superseded handoff/debug notes.

Core Python modules:

- `rag_ime/local_sqlite_core.py`: SQLite/FTS5/vector-ish local RAG and memory
  store; feedback, phrase stats, cleanup, RAG organization.
- `rag_ime/rime_sidecar.py`: HTTP sidecar logic for `/api/rime-suggest` and
  `/api/rime-select`, model/RAG/Rime merge, trigger policy, display payloads.
- `rag_ime/prediction_first.py`: prediction-first source-lane merge logic.
- `rag_ime/predictor.py`: predictor client abstraction and candidate parsing for
  OpenAI-compatible/Ollama/MLX services.
- `rag_ime/mlx_predictor_server.py`: resident local MLX model server.
- `rag_ime/memory_generator.py`: offline `x1top` / `x1api-compatible`
  memory/RAG/lexicon distillation.
- `rag_ime/debug_server.py`: debug and management endpoints.
- `rag_ime/history_context.py`: bounded recent-context construction and
  fingerprints.
- `rag_ime/models.py`: core dataclasses including input events, suggestions,
  model predictions, Rime snapshots, display items.

macOS frontend:

- `squirrel-patches/0001-add-rag-ime-sidecar.patch`: product route. This patches
  upstream Squirrel to call the local sidecar and show side candidates.
- `squirrel-patches/README.md`: patch preparation and Squirrel build notes.
- `macos/RagImeMac/`: debug-only native InputMethodKit/AppKit harness. Do not
  treat this as the shipping IME.

Scripts:

- `scripts/prepare_squirrel_workspace.sh`: clone/apply Squirrel patch.
- `scripts/build_patched_squirrel.sh`: build/install patched Squirrel.
- `scripts/restart_rag_ime_runtime.sh`: restart local MLX predictor + sidecar.
- `scripts/doctor_squirrel_integration.sh`: integration readiness doctor.
- `scripts/verify_squirrel_foreground_trace.sh`: foreground trace verifier.
- `scripts/soak_squirrel_foreground_trace.sh`: longer real-foreground soak run
  that emits a machine-readable report.
- `scripts/check_squirrel_frontend_trace.py`: parse frontend JSONL trace.
- `scripts/check_squirrel_soak_report.py`: validate the soak JSON report and
  fail on stale application, wrong commit, or missing commit barrier events.
- `scripts/check_sichuan_fuzzy_profile.sh`: JSON checker for the managed
  Sichuan mild fuzzy-pinyin profile.
- `scripts/apply_sichuan_fuzzy_profile.sh`: dry-run/apply/backup installer for
  the managed Sichuan mild fuzzy-pinyin profile.
- `scripts/install_sichuan_fuzzy_pinyin.sh`: compatibility wrapper around
  `apply_sichuan_fuzzy_profile.sh --apply`.
- `scripts/install_sidecar_launch_agent.sh`: user LaunchAgent for sidecar.
- `scripts/install_mlx_predictor_launch_agent.sh`: user LaunchAgent for MLX.
- `scripts/benchmark_mlx_model_matrix.py`: local model benchmark helper.
- `scripts/run_product_readiness_gate.sh`: one-command product-readiness gate.
  Default path runs unit tests, `scripts/acceptance.py`, and backend
  `quality-gate`; `RAG_IME_REQUIRE_MACOS_FRONTEND=1` also requires real
  Squirrel tryout and soak-report evidence.

Useful PR-5 review CLI now present in `rag_ime/cli.py`:

- `seed-eval-cases --cases-file ...`: seed deterministic curated eval memories
  into a local DB for reproducible product quality gates.
- `governance-report`: inspect active suppressions/tombstones.
- `tombstone`: add one manual tombstone row to the local governance store.
- `anti-echo-demo`: run ad-hoc candidate texts through the anti-echo governor
  without needing a live Squirrel session.

New PR-6 cleanup CLI now present in `rag_ime/cli.py`:

- `cleanup-preview`: build a true dry-run cleanup diff file.
- `cleanup-validate`: inspect a run/file and reject unsafe diffs before apply.
- `cleanup-apply --apply`: explicit-confirmation apply gate.
- `cleanup-rollback`: revert an applied cleanup run by `runId`.

New PR-9 quality/rerank CLI now present in `rag_ime/cli.py`:

- `model-matrix-eval`: alias of `eval-model-matrix` using the roadmap command
  name; reports `productMetrics` in each model row.
- `rerank-demo`: rank ad-hoc `source:text` or JSON candidates and emit source
  counts, score breakdowns, echo/duplicate flags, and Rime fallback status.

New PR-10 management API now present in `rag_ime/debug_server.py`:

- `GET /api/candidates/explain?query=...`
- `GET /api/history?limit=100&project=...`
- `POST /api/history/tombstone`
- `GET /api/memories?status=pending`
- `POST /api/memories/action`
- `GET /api/lexicon?status=pending`
- `POST /api/lexicon/action`
- `GET /api/cleanup-diff?id=...`
- `POST /api/cleanup-diff/apply`
- `POST /api/cleanup-diff/rollback`

## Code Path Map

### Foreground Squirrel path

File: `squirrel-patches/0001-add-rag-ime-sidecar.patch`

Key responsibilities:

- Adds `RagImeSidecarClient.swift` and `RagImeSidecarModels.swift` to Squirrel.
- Captures Rime raw input, preedit, candidate page, labels, comments, and
  committed context.
- Schedules sidecar requests with request fingerprints and generation IDs.
- Applies sidecar `displayCandidates` only if current foreground context still
  matches.
- Holds post-commit candidates long enough for human selection.
- Routes number keys through visible `displayCandidates` before inserting
  literal digits.
- Records side-candidate commit and accepted RAG actions via `/rime-select`.
- Writes frontend trace to `~/Library/Logs/RagIme/squirrel-frontend.jsonl`.

Notable patch regions from current patch file:

- Sidecar client model definitions start around patch lines 188 and 525.
- State fields include `ragImeDisplayCandidates`, `ragImeDisplayRawInput`,
  `ragImeDisplayPreedit`, `ragImeDisplaySessionFingerprint`,
  `ragImeInputGeneration`, and holdover durations around patch lines 761-783.
- Delete-key invalidation and number-key routing appear around patch lines
  791-803.
- `selectCandidate` side-candidate commit path appears around patch lines
  810-855.
- `selectRagImeSideCandidate(forKey:)` appears around patch lines 939-963.
- `refreshRagImeSidecar(...)` request construction appears around patch lines
  965-1068.

Acceptance evidence should come from frontend trace events such as:

- `sidecar_request_scheduled`
- `sidecar_response_applied`
- `panel_display_candidates`
- `number_key_route`
- `side_candidate_commit`
- `committed_context_resynced_after_delete`
- `sidecar_response_dropped`

The frontend and soak trace checkers now support `--require-delete-resync`.
That gate pairs `display_invalidated_by_input_change(reason=delete_key)` with
`committed_context_resynced_after_delete` by timestamp/input generation, so a
real foreground trace can explicitly prove Backspace/Delete rebuilt context
from the actual client state. The Squirrel patch now includes
`frontendRevision`, `selectionEpoch`, and `committedContextHash` on the resync
event.

The same gate now also requires a later `sidecar_request_scheduled` or
`sidecar_response_applied` event to carry the resynced `committedContextHash`.
If a post-delete request/response carries the old hash, the checker reports
`post_delete_context_hash_mismatch` and fails. This is the concrete guard for
the user's complaint that Backspace/Delete looked resynced while LLM/RAG still
used deleted text.

Prediction stability is now a first-class layer. `rag_ime/prediction_anchors.py`
splits identity into `hardContextAnchor`, `queryAnchor`, and `displayAnchor` so
Backspace/Delete/app/input-source changes can hard-clear old candidates while
ordinary preedit/Rime candidate changes can refresh without flashing the panel.
`rag_ime/prediction_stability.py` creates `StableCandidateSnapshot` records and
returns explicit actions such as `fresh`, `soft_hold`, `reuse_last_good`,
`soft_hide`, and `hard_clear`. It also handles progressive follow-up: same
visible-prefix candidates may append under the same `snapshotId`, while any
follow-up that would reorder or replace visible ordinals becomes
`progressive_replace` with a new `snapshotId`. PR-E prefix-compatible holdover
filtering has started too: if no fresh candidates are available during the same
composition transaction, stale model/RAG/memory rows are filtered by the active
short pinyin prefix before reuse, and any removal creates a new `snapshotId` for
atomic panel replacement. `PredictionManager.render(...)` applies this only in
post-commit and prefix-constrained prediction modes, then exposes the diagnostics
through `predictionFirst.policy.stability` and anchor fields through
`predictionSession`.

The sidecar now also exposes PR-B/PR-C/PR-D payload contracts:
`refreshDecision`, `showDecision`, and `keyPolicy` are top-level response
fields; `displayCandidates[]` includes `snapshotId`, `candidateStableId`,
`candidateOrdinal`, `visibleLabel`, `sourceBadge`, `sourceStability`, anchors,
and snapshot TTL fields. The Squirrel patch decodes these fields and only routes
ordinary number keys when `keyPolicy.numberKeys == "select_visible_candidate"`,
so post-commit predictions use `numberKeys=pass_through`. The patch also routes
post-commit `Tab` to the top prediction only when
`keyPolicy.tab == "accept_top_prediction"` and routes `Option+number` by ordinal
only when `keyPolicy.optionNumber == "select_prediction_by_ordinal"`. The patch
now rejects stale candidate selection when `snapshotId`, `candidateOrdinal`,
`candidateStableId`, candidate expiry, session fingerprint, or foreground
transaction metadata no longer match; the frontend trace checker compares the
same snapshot-lock fields before accepting a number-key route/commit pair.
PR-E has also started: active composition refreshes now pass through a small
per-session debounce/coalescing guard keyed by hard context and query family.
When a request is coalesced inside `RAG_IME_REFRESH_DEBOUNCE_MS`, the sidecar
skips RAG/LLM lane execution but still calls `PredictionManager` so an existing
legal snapshot can remain visible.
Prediction explainability now has an explicit response-to-frontend path:
`predictionTraceEvents` is emitted by the sidecar, decoded by the Squirrel patch,
and forwarded into the frontend JSONL trace. The events include anchors,
snapshot ids, source counts, action/reason, debounce/holdover flags, and lane
timeout fields without raw text by default. Progressive snapshot actions emit
`candidate_snapshot_progressive_append` or
`candidate_snapshot_progressive_replace`.

Latest stability proof coverage maps directly to the user's foreground
complaints: RAG empty/model timeout no longer blanks a legal model snapshot,
trigger-skipped refresh debounce soft-holds during the min-visible window, and
QueryAnchor changes refresh without immediately emptying the panel. Strict
hard-clear cases are covered for app switch, input-source switch, selection
epoch change, delete/backspace committed-context hash change, and composition
hash change. Holdover/reused-last-good candidates are bound with
`sourceStability=reused_last_good` plus `snapshotId` so Squirrel can render them
as dim/stable instead of pretending they are fresh.

### Sidecar merge path

File: `rag_ime/rime_sidecar.py`

Important functions / structures:

- `RimeSideCandidateTriggerDecision` around line 231.
- `_ModelPredictionHoldover` around line 237.
- The main response payload assembly around lines 450-470 includes:
  `modelPredictions`, `ragCandidates`, `displayCandidates`,
  `predictionSession`, `selectionActions`, and `mergePolicy`.
- `suggest_rag_with_latency_budget(...)` around line 491.
- `realtime_model_candidate_limit(...)` around line 874.
- RAG repeat/context filters around lines 1052 and 1839.
- RAG/model lane status helpers around lines 1872 and 1891.
- Display payload helpers around lines 2826-2957.
- `_prediction_session_expiry_ms(...)` around line 2897.

Sidecar principle:

```text
Build semantic query from actual foreground state
  -> decide whether side candidates should refresh
  -> retrieve RAG with quality gates and overfetch
  -> request local model when useful
  -> merge model/RAG/Rime into displayCandidates
  -> attach sessionFingerprint and selection metadata
```

### Local MLX predictor path

File: `rag_ime/mlx_predictor_server.py`

Important functions:

- `class MlxLmEngine` around line 140.
- `MlxLmEngine.predict(...)` around line 201.
- `predict_no_input_continuation_branches(...)` around line 344.
- `predict_next_token_logits(...)` around line 491.
- `_stream_text_with_generate_step(...)` around line 657.
- `_build_mlx_dynamic_prompt(...)` around line 1081.
- `_top_logprob_indices(...)` around line 1487.
- `_continuation_branch_specs(...)` around line 1632.

Current implementation:

- Uses `mlx-lm` to load model/tokenizer in a resident server.
- This is not a hand-written Transformer runtime.
- The project-owned layer builds prompts, calls `generate_step()`, reads
  next-token `logprobs`, filters candidates, and converts outputs to IME
  candidates.
- Current `predict_next_token_logits()` probes the next-token logits with
  `max_tokens=1`.
- Current `no_input_prediction` can produce multiple candidates through
  `continuation-branches`, but this is a service-layer generation strategy, not
  true KV-cache sequence forking.
- Current doctor has reported `sequenceFork=false`.

Desired next local-model architecture:

```text
actual foreground context
-> tokenize
-> run prompt through local MLX model
-> inspect next-token logprobs
-> take top 3 seed tokens
-> fork or replay each seed as an independent continuation branch
-> extend each branch for a short phrase budget
-> decode into 3 LLM candidates
-> filter echo/prompt fragments/generic words
-> rerank with source diagnostics
-> mix with RAG and dictionary candidates using distinct source colors
```

Implementation advice:

- Do not modify hidden-layer internals before softmax unless absolutely needed.
- Work at the `generate_step()`/`logprobs` layer.
- First practical implementation can replay top-3 seed tokens against the
  prepared prompt cache if MLX-LM does not expose cheap cache cloning.
- Later optimization should use true KV cache copy/fork if available.
- Output should be phrase-oriented, not isolated high-probability filler tokens.

### Local RAG / memory path

File: `rag_ime/local_sqlite_core.py`

Important functions:

- `class LocalSqliteCoreClient` around line 54.
- `initialize()` around line 84.
- `record_event(...)` around line 246.
- `suggest_for_input(...)` around line 331.
- `retrieve_memories(...)` around line 362.
- `_retrieve_candidate_rows(...)` around line 413.
- `apply_action(...)` around line 449.
- `build_agent_context(...)` around line 493.
- `recent_input_context(...)` around line 514.
- `rebuild_vector_index(...)` around line 610.
- `list_memory_events(...)` around line 678.
- `core_optimization_snapshot(...)` around line 748.
- `hide_codex_history_noise(...)` around line 829.
- `organize_rag_database(...)` around line 910.

Data principles:

- SQLite event log stores committed input and memory events.
- FTS5 and optional embeddings support retrieval.
- Feedback actions such as accepted/skipped/downranked/pinned influence ranking.
- Generated one-off side candidates should not immediately become strong RAG
  memory without repeated acceptance, pinning, or frequency evidence.
- RAG must not dominate simply because a row is recent if the active context no
  longer supports it.

Offline cleanup:

- `x1top` is the high-intelligence GPT-series offline lane. It can be used for
  memory distillation, RAG organization, phrase extraction, and cleanup
  suggestions through the existing `x1api.top`-compatible endpoint/config
  layer.
- `x1top` must not be configured as the realtime predictor.
- Realtime predictor config must resolve to a loopback base URL; explicit
  `RAG_IME_PREDICTOR_ENV` files that point at `x1api.top`, `x2app.top`, or
  other remote OpenAI-compatible URLs are ignored for `/rime-suggest`.
- Destructive cleanup should be advisory/dry-run until reviewed.

### Predictor client path

File: `rag_ime/predictor.py`

Responsibilities:

- Provider configs for OpenAI-compatible, Ollama, and MLX service.
- Candidate parsing from JSON, space-separated output, and raw generation.
- Low-value/meta candidate filtering.
- Environment-boundary logic so legacy `X1API_*` or generic API variables do
  not automatically configure realtime prediction.
- Predictor doctor and latency advice.

Important boundary:

```text
RAG_IME_PREDICTOR_* = realtime local predictor config
X1API_* / RAG_IME_AI_* = offline memory/RAG/lexicon cleanup config
```

### Debug server path

File: `rag_ime/debug_server.py`

Useful endpoints / methods:

- `health()`
- `rebuild_vector_index()`
- `memory_history()`
- `organize_rag_database()`
- `generate_memory()`
- `predictor_ttfc()`
- `cache_probe()`
- `rime_suggest()`
- `rime_select()`

Use it for diagnosing whether the model lane, RAG lane, cache, vector index, and
candidate source diagnostics are active.

## Key Code Excerpts For Pro

These excerpts are included because the user explicitly needs the Pro model to
read code even when repository browsing is unavailable. They are shortened, but
they preserve the current contracts and the next edit points.

### Prediction display stability layer

Files: `rag_ime/prediction_anchors.py`, `rag_ime/prediction_stability.py`,
`rag_ime/prediction_manager.py`

```python
@dataclass(frozen=True)
class PredictionAnchors:
    hard_context_anchor: str
    query_anchor: str
    display_anchor: str
    hard_fields: dict[str, object]
    query_fields: dict[str, object]
    display_fields: dict[str, object]


def build_prediction_anchors_from_snapshot(
    *,
    snapshot: RimeContextSnapshot,
    mode: str,
    semantic_query: str = "",
    query_basis: str = "",
    stable_short_pinyin_prefix: str = "",
) -> PredictionAnchors:
    transaction = snapshot.frontend_transaction
    committed_hash = transaction.committed_context_hash or stable_text_hash(snapshot.committed_context)
    composition_hash = transaction.composition_hash or stable_text_hash(snapshot.preedit or snapshot.raw_input)
    return build_prediction_anchors(
        session_id=snapshot.session_id,
        panel_session_id=transaction.panel_session_id,
        front_app_bundle_id=transaction.front_app_bundle_id or snapshot.app,
        input_source_id=transaction.input_source_id,
        selection_epoch=transaction.selection_epoch,
        committed_context_hash=committed_hash,
        composition_hash=composition_hash,
        mode=mode,
        semantic_query=semantic_query,
        query_basis=query_basis,
        stable_short_pinyin_prefix=stable_short_pinyin_prefix,
        preedit=snapshot.preedit or snapshot.raw_input,
        rime_candidates=snapshot.candidates,
    )
```

```python
@dataclass(frozen=True)
class StableCandidateSnapshot:
    snapshot_id: str
    generation: int
    hard_context_anchor: str
    query_anchor: str
    display_anchor: str
    mode: str
    min_visible_until_ms: int
    expires_at_ms: int
    candidates: tuple[object, ...]
    source_summary: dict[str, int]
    lane_status: dict[str, object]
    reused_last_good: bool = False
    holdover_hit: bool = False
    stale_level: str = "fresh"


def render_stable_prediction_panel(...):
    if hard_clear_reason:
        return None, cleared_state, {"action": "hard_clear", ...}
    if fresh_candidates and progressive_update and previous:
        if previous.hard_context_anchor != anchors.hard_context_anchor:
            pass  # normal fresh path handles the hard boundary
        elif previous.display_anchor == anchors.display_anchor and not expired:
            if fresh_keys start with previous_keys:
                # Existing visible ordinals remain identical. Only append empty slots.
                return same_snapshot_id_with_appended_candidates, state, {
                    "action": "progressive_append",
                    "preservedOrdinalCount": len(previous_keys),
                    "appendedCandidateCount": appended_count,
                }
            return new_snapshot, state, {
                "action": "progressive_replace",
                "reason": "progressive_reordered_visible_ordinals",
            }
    if fresh_candidates:
        return fresh_snapshot, next_state, {"action": "fresh", ...}
    if previous.hard_context_anchor != anchors.hard_context_anchor:
        return None, cleared_state, {"action": "hard_clear", ...}
    if previous.display_anchor != anchors.display_anchor or now > previous.expires_at_ms:
        return None, next_state, {"action": "soft_hide", ...}
    if mode_family == "prefix_composing" and no_fresh_candidates:
        kept = [candidate for candidate in previous.candidates if prefix_compatible(candidate, active_prefix)]
        if kept != previous.candidates:
            # Removal changes visible ordinals, so this is a new snapshot.
            return new_snapshot_with_kept_candidates, state, {
                "action": "prefix_filter",
                "reason": "prefix_incompatible_candidates_removed",
                "prefixRemovedCandidateCount": removed_count,
            }
    if now <= previous.min_visible_until_ms:
        return reused_snapshot, next_state, {"action": "soft_hold", ...}
    if lane_empty_or_timed_out:
        return reused_snapshot, next_state, {"action": "reuse_last_good", ...}
```

```python
if merge_result.mode in {InputMode.POST_COMMIT_PREDICTING, InputMode.PREFIX_CONSTRAINED_COMPOSING}:
    stable_snapshot, self._panel_state, stability = render_stable_prediction_panel(
        state=self._panel_state,
        anchors=anchors,
        mode=merge_result.mode.value,
        fresh_candidates=merge_result.display_candidates,
        trigger_decision={
            "sourceUpdate": source_update,
            "candidatePoolStale": candidate_pool_stale,
            "candidatePoolActive": bool(active_model_predictions or active_suggestions),
        },
        rag_lane={"called": source_update, "suggestionCount": len(active_suggestions)},
        model_lane={"called": source_update, "predictionCount": len(active_model_predictions)},
        now_ms=now_ms,
        progressive_update=snapshot.progressive_follow_up,
        max_visible_candidates=snapshot.max_visible_candidates,
    )
    display_candidates = tuple(item for item in stable_snapshot.candidates if isinstance(item, SideCandidateDisplayItem)) if stable_snapshot else ()
    merge_result = replace(
        merge_result,
        display_candidates=display_candidates,
        policy={
            **merge_result.policy,
            "panelVisible": bool(display_candidates),
            "predictionPanelVisible": side_count > 0,
            "shouldClearPredictionPanel": side_count <= 0,
            "stabilityAction": str(stability.get("action") or ""),
            "stabilityReason": str(stability.get("reason") or ""),
            "stabilityReusedLastGood": bool(stable_snapshot.reused_last_good if stable_snapshot else False),
            "stabilitySnapshotId": stable_snapshot.snapshot_id if stable_snapshot else "",
        },
    )
```

### Prediction-First Display Contract

File: `rag_ime/prediction_first.py`

The visible candidate text is now bounded separately from commit text. This is
important for IME usability: a RAG or memory candidate must not render a whole
evidence sentence in the candidate bar, but selecting it should still commit the
full intended phrase when appropriate.

```python
_COMPOSITION_DISPLAY_LIMITS = {"model": 16, "rag": 18, "memory": 18}
_POST_COMMIT_DISPLAY_LIMITS = {"model": 22, "rag": 20, "memory": 20}

def _side_display_item(candidate, zero_based_index, mode, prefix):
    display_text, truncated = _bounded_side_display_text(
        candidate.display_text,
        source_type=candidate.source_type,
        mode=mode,
    )
    metadata["display_text_truncated"] = truncated
    if truncated:
        metadata["full_display_text"] = candidate.display_text
        metadata["display_text_limit"] = _side_display_text_limit(candidate.source_type, mode)
    return SideCandidateDisplayItem(
        text=display_text,
        insert_text=candidate.insert_text,
        source_type=candidate.source_type,
        ...
    )
```

### Snapshot lock and key policy payload

File: `rag_ime/rime_sidecar.py`

```python
def key_policy_for_prediction_session(prediction_session_payload: Mapping[str, object]) -> dict[str, object]:
    phase = _string(prediction_session_payload.get("phase"))
    input_mode = _string(prediction_session_payload.get("inputMode"))
    if phase == "post_commit" or input_mode == "post_commit_predicting":
        return {
            "numberKeys": "pass_through",
            "tab": "accept_top_prediction",
            "optionNumber": "select_prediction_by_ordinal",
            "escape": "dismiss_prediction",
        }
    if phase in {"prefix_constrained", "anchor_composing"} or input_mode in {
        "prefix_constrained_composing",
        "anchor_composing",
    }:
        return {
            "numberKeys": "select_visible_candidate",
            "tab": "page_or_accept_by_rime_mode",
            "optionNumber": "select_side_candidate",
            "escape": "dismiss_side_candidates",
        }
    return {
        "numberKeys": "pass_through",
        "tab": "pass_through_or_rime",
        "optionNumber": "pass_through",
        "escape": "pass_through_or_clear_rime",
    }
```

```python
metadata.update(
    {
        "snapshotId": stable_snapshot_id,
        "stableSnapshotId": stable_snapshot_id,
        "snapshotGeneration": snapshot_generation,
        "candidateStableId": _candidate_stable_id(item, snapshot_id=stable_snapshot_id),
        "candidateOrdinal": ordinal,
        "visibleLabel": item.label,
        "sourceBadge": candidate_source_badge(item.source_type),
        "sourceStability": source_stability,
        "expiresAtMs": expires_at_ms,
        "minVisibleUntilMs": min_visible_until_ms,
        "keyPolicy": dict(key_policy or {}),
    }
)
```

Squirrel patch contract excerpt:

```swift
let keyPolicy: RagImeKeyPolicyPayload?
let candidateOrdinal: Int?
let candidateStableId: String?
let snapshotId: String?
let sourceBadge: String?
let sourceStability: String?

if !modifiers.contains(.control)
  && !modifiers.contains(.option)
  && ragImeDisplayNumberKeyPolicy == "select_visible_candidate"
  && selectRagImeSideCandidate(forKey: String(char)) {
  return true
}

func canSelectRagImeDisplayCandidate(_ candidate: RagImeDisplayCandidate) -> Bool {
  guard ragImeDisplaySessionStillLive() else { return false }
  guard !ragImeDisplaySessionFingerprint.isEmpty else { return true }
  guard ragImeDisplayCandidateSessionFingerprint(candidate) == ragImeDisplaySessionFingerprint else { return false }
  if !ragImeDisplaySnapshotId.isEmpty {
    guard candidate.snapshotId == ragImeDisplaySnapshotId else { return false }
  }
  if let ordinal = candidate.candidateOrdinal, ordinal > 0 {
    guard ordinal <= ragImeDisplayCandidates.count else { return false }
    guard ragImeDisplayCandidates[ordinal - 1].candidateStableId == candidate.candidateStableId else { return false }
  }
  if let expiresAtMs = candidate.expiresAtMs, expiresAtMs > 0 {
    let nowMs = Int(Date().timeIntervalSince1970 * 1000)
    guard nowMs <= expiresAtMs else { return false }
  }
  ...
}
```

### Composition refresh debounce

File: `rag_ime/rime_sidecar.py`

```python
trigger_decision, refresh_debounce = apply_refresh_debounce(
    snapshot=snapshot,
    trigger_decision=trigger_decision,
    semantic_query=semantic_query,
    query_basis=query_basis,
    default_project=default_project,
)
if trigger_decision.should_refresh:
    suggestions, rag_lane, model_predictions, model_lane, progressive_state = run_side_lanes_with_latency_budget(...)
```

```python
def apply_refresh_debounce(...):
    if not trigger_decision.should_refresh or debounce_ms <= 0:
        return trigger_decision, {"debounced": False, "debounceMs": debounce_ms}
    if snapshot.progressive_follow_up or compact_whitespace(snapshot.commit_text_preview):
        return trigger_decision, {"debounced": False, "reason": "post_commit_or_followup"}
    if not compact_whitespace(snapshot.raw_input or snapshot.preedit):
        return trigger_decision, {"debounced": False, "reason": "no_active_composition"}

    key = (project, app, session_id, anchors.hard_context_anchor, query_family)
    if previous is not None and age_ms <= debounce_ms:
        return RimeSideCandidateTriggerDecision(False, "skip: refresh debounce coalesced"), {
            "debounced": True,
            "coalescedWithAgeMs": age_ms,
            "debounceKey": _short_stable_id(*key),
        }
```

### Prediction Trace Events

Files: `rag_ime/rime_sidecar.py`,
`squirrel-patches/0001-add-rag-ime-sidecar.patch`,
`scripts/check_squirrel_frontend_trace.py`

```python
prediction_trace_events = prediction_trace_events_payload(
    prediction_session=prediction_session_payload,
    refresh_decision=refresh_decision,
    show_decision=show_decision,
    rag_lane=rag_lane,
    model_lane=model_lane,
    display_candidates=display_candidates,
)
```

Event names include:

```text
prediction_anchor_computed
prediction_refresh_decision
prediction_show_decision
prediction_snapshot_created
prediction_snapshot_reused
prediction_panel_soft_hold
prediction_panel_soft_hide
prediction_panel_hard_clear
prediction_empty_lane_did_not_clear_panel
prediction_lane_timeout_with_holdover
prediction_lane_timeout_without_holdover
candidate_snapshot_progressive_append
candidate_snapshot_progressive_replace
prediction_prefix_filter_applied
```

Squirrel forwarding contract:

```swift
struct RagImePredictionTraceEvent: Codable {
  let event: String
  let fields: [String: RagImeJSONValue]
}

func traceRagImePredictionEvents(_ events: [RagImePredictionTraceEvent]?) {
  guard let events else { return }
  for item in events {
    traceRagImeFrontendEvent(item.event, fields: ragImeJSONValueDictionary(item.fields))
  }
}
```

### PR-1 frontend transaction model

File: `rag_ime/models.py`

```python
@dataclass(frozen=True)
class FrontendTransaction:
    """Frontend state identity that sidecar responses and selections must echo."""

    frontend_revision: int = 0
    selection_epoch: int = 0
    front_app_bundle_id: str = ""
    input_source_id: str = ""
    composition_hash: str = ""
    committed_context_hash: str = ""
    panel_session_id: str = ""
    created_at_ms: int = 0


@dataclass(frozen=True)
class RimeContextSnapshot:
    session_id: str
    request_seq: int
    raw_input: str = ""
    preedit: str = ""
    committed_context: str = ""
    candidates: tuple[RimeCandidate, ...] = ()
    page: int = 0
    force_side_candidates: bool = False
    progressive_follow_up: bool = False
    frontend_transaction: FrontendTransaction = field(default_factory=FrontendTransaction)
```

Hash helper:

```python
def stable_text_hash(text: str) -> str:
    normalized = compact_whitespace(text or "")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"sha256:{digest}"
```

### PR-1 sidecar request parsing and candidate binding

File: `rag_ime/rime_sidecar.py`

```python
raw_input = _string(payload.get("rawInput") or payload.get("currentInput"))
preedit = _string(payload.get("preedit"))
committed_context = _string(payload.get("committedContext") or payload.get("recentContext"))

return RimeContextSnapshot(
    session_id=_string(payload.get("sessionId")) or "default",
    request_seq=_bounded_int(payload.get("requestSeq"), default=0, minimum=0, maximum=2**63 - 1),
    raw_input=raw_input,
    preedit=preedit,
    committed_context=committed_context,
    frontend_transaction=_frontend_transaction_from_payload(
        payload=payload,
        rime_context=rime_context,
        raw_input=raw_input,
        preedit=preedit,
        committed_context=committed_context,
    ),
)
```

```python
def frontend_transaction_to_payload(transaction: FrontendTransaction) -> dict[str, object]:
    return {
        "frontendRevision": transaction.frontend_revision,
        "selectionEpoch": transaction.selection_epoch,
        "frontAppBundleId": transaction.front_app_bundle_id,
        "inputSourceId": transaction.input_source_id,
        "compositionHash": transaction.composition_hash,
        "committedContextHash": transaction.committed_context_hash,
        "panelSessionId": transaction.panel_session_id,
        "createdAtMs": transaction.created_at_ms,
    }
```

```python
metadata.update(
    {
        "sessionFingerprint": session_fingerprint,
        "contextFingerprint": context_fingerprint,
        "requestSeq": snapshot.request_seq,
        "sessionId": snapshot.session_id,
        "frontendRevision": transaction.frontend_revision,
        "selectionEpoch": transaction.selection_epoch,
        "frontAppBundleId": transaction.front_app_bundle_id,
        "inputSourceId": transaction.input_source_id,
        "compositionHash": transaction.composition_hash,
        "committedContextHash": transaction.committed_context_hash,
        "panelSessionId": transaction.panel_session_id,
    }
)
```

### PR-1 Squirrel patch transaction checks

File: `squirrel-patches/0001-add-rag-ime-sidecar.patch`

```swift
struct RagImeSidecarRequest: Codable {
  let frontendBuild: String
  let schemaVersion: String
  let predictionFirstMerge: Bool
  let sessionId: String
  let requestSeq: Int
  let frontendRevision: Int
  let selectionEpoch: Int
  let frontAppBundleId: String
  let inputSourceId: String
  let compositionHash: String
  let committedContextHash: String
  let panelSessionId: String
  let rawInput: String
  let preedit: String
  let committedContext: String
  let rimeContext: RagImeRimeContextPayload
}
```

```swift
guard response.frontendRevision == request.frontendRevision else {
  dropRagImeSidecarResponse("frontend_revision_mismatch", response: response, request: request, fingerprint: fingerprint)
  return
}
guard response.selectionEpoch == request.selectionEpoch else {
  dropRagImeSidecarResponse("selection_epoch_mismatch", response: response, request: request, fingerprint: fingerprint)
  return
}
guard response.compositionHash == request.compositionHash else {
  dropRagImeSidecarResponse("composition_hash_mismatch", response: response, request: request, fingerprint: fingerprint)
  return
}
guard response.committedContextHash == request.committedContextHash else {
  dropRagImeSidecarResponse("committed_context_hash_mismatch", response: response, request: request, fingerprint: fingerprint)
  return
}
guard response.panelSessionId == request.panelSessionId else {
  dropRagImeSidecarResponse("panel_session_mismatch", response: response, request: request, fingerprint: fingerprint)
  return
}
guard response.frontendRevision == ragImeFrontendRevision else {
  dropRagImeSidecarResponse("live_frontend_revision_changed", response: response, request: request, fingerprint: fingerprint)
  return
}
guard response.selectionEpoch == ragImeSelectionEpoch else {
  dropRagImeSidecarResponse("live_selection_epoch_changed", response: response, request: request, fingerprint: fingerprint)
  return
}
```

Default frontend trace is privacy preserving:

```swift
func ragImeSanitizedTraceValue(_ value: Any, key: String, includeText: Bool) -> Any {
  if includeText {
    return value
  }
  if let text = value as? String {
    guard ragImeTraceKeyCarriesUserText(key), !text.isEmpty else { return text }
    return [
      "chars": ragImeCompactWhitespace(text).count,
      "hash": ragImeStableTextHash(text),
    ] as [String: Any]
  }
  ...
}
```

### PR-7 source badge/color payload contract

File: `rag_ime/rime_sidecar.py`

```python
_SOURCE_BADGE_MAP = {
    "rime": "词",
    "model": "模",
    "rag": "查",
    "memory": "忆",
    "raw_english": "input",
}

_SOURCE_COLOR_TOKEN_MAP = {
    "rime": "rimeOrange",
    "model": "modelBlue",
    "rag": "ragTeal",
    "memory": "memoryPurple",
    "raw_english": "rawGray",
}

def display_item_to_payload(item: SideCandidateDisplayItem) -> dict[str, object]:
    selection_key = item.label
    source_badge = candidate_source_badge(item.source_type)
    color_token = candidate_color_token(item.source_type)
    comment = item.comment if candidate_diagnostics_enabled() else ""
    return {
        "label": item.label,
        "selectionKey": selection_key,
        "selectionRank": _candidate_rank(selection_key),
        "text": item.text,
        "insertText": item.insert_text,
        "sourceType": item.source_type,
        "selectionAction": item.selection_action,
        "sourceIndex": item.source_index,
        "comment": comment,
        "badge": source_badge,
        "colorToken": color_token,
        "displayLayout": item.display_layout,
        "displayLane": item.display_lane or item.source_type,
        "metadata": dict(item.metadata),
    }
```

File: `squirrel-patches/0001-add-rag-ime-sidecar.patch`

```swift
struct RagImeDisplayCandidate: Codable, Hashable {
  let label: String
  let selectionKey: String?
  let selectionRank: Int?
  let text: String
  let insertText: String
  let sourceType: String
  let selectionAction: String
  let sourceIndex: Int
  let comment: String
  let badge: String?
  let colorToken: String?
  let displayLayout: String?
  let displayLane: String?
  let metadata: [String: RagImeJSONValue]
}

func ragImeDisplayBadge(for candidate: RagImeDisplayCandidate) -> String {
  guard ragImeCandidateSourceBadgesEnabled() else { return "" }
  if let badge = candidate.badge, !badge.isEmpty { return badge }
  switch candidate.sourceType {
  case "model": return "模"
  case "rag": return "查"
  case "memory": return "忆"
  case "rime": return "词"
  case "raw_english": return "input"
  default: return candidate.sourceType
  }
}
```

File: `scripts/check_squirrel_frontend_trace.py`

```python
SOURCE_BADGES = {
    "rime": "词",
    "model": "模",
    "rag": "查",
    "memory": "忆",
    "raw_english": "input",
}

def candidate_source_visuals_match(candidate: dict[str, Any]) -> bool:
    source_type = str(candidate.get("sourceType") or "")
    expected_badge = SOURCE_BADGES.get(source_type)
    expected_color = SOURCE_COLOR_TOKENS.get(source_type)
    if expected_badge is None or expected_color is None:
        return source_type in {"", "side"}
    return (
        str(candidate.get("badge") or "") == expected_badge
        and str(candidate.get("colorToken") or "") == expected_color
    )
```

### Local MLX next-token logits entry point

File: `rag_ime/mlx_predictor_server.py`

```python
def predict(
    self,
    *,
    current_input: str,
    recent_context: str,
    max_candidates: int,
    max_tokens: int,
    temperature: float,
    top_p: float,
    request_type: str = PREDICTION_REQUEST_GENERIC,
    rime_candidates: tuple[str, ...] = (),
    stream_first_candidate: bool = False,
    request_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ...
    logits_candidates = self.predict_next_token_logits(
        current_input=current_input,
        recent_context=recent_context,
        max_candidates=max_candidates,
        request_type=resolved_request_type,
        rime_candidates=rime_candidate_tuple,
        request_metadata=request_metadata,
    )
    if _logits_candidates_are_ime_quality(logits_candidates["candidates"], max_candidates=max_candidates):
        ...

    if resolved_request_type == PREDICTION_REQUEST_NO_INPUT and not stream_first_candidate:
        seeded_replay_payload = self.predict_no_input_seeded_prompt_replay(
            current_input=current_input,
            recent_context=recent_context,
            max_candidates=max_candidates,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            started=started,
            logits_candidates=logits_candidates,
            request_metadata=request_metadata,
        )
        if seeded_replay_payload is not None and seeded_replay_payload.get("candidates"):
            return seeded_replay_payload
        return self.predict_no_input_continuation_branches(...)
```

The PR-4 implementation is now partially in-tree. The predictor no longer stops
at "this is where seeded replay should go"; it actually tries a seeded replay
path before the older continuation-branch fallback.

Actual seeded replay code path:

```python
def predict_no_input_seeded_prompt_replay(
    self,
    *,
    current_input: str,
    recent_context: str,
    max_candidates: int,
    max_tokens: int,
    temperature: float,
    top_p: float,
    started: float,
    logits_candidates: dict[str, Any],
    request_metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    seeds = _seed_replay_specs_from_logits(
        logits_candidates.get("candidateScores"),
        max_seeds=max(1, min(3, int(max_candidates))),
    )
    if not seeds:
        return None
    ...
    for seed in seeds:
        raw_text = "".join(
            self._stream_text_with_generate_step(
                prompt=_build_seeded_replay_prompt(
                    recent_context=recent_context,
                    seed_text=seed_text,
                ),
                max_tokens=per_seed_max_tokens,
                temperature=replay_temperature,
                top_p=top_p,
            )
        )
        candidate = _seeded_replay_candidate(
            seed_text=seed_text,
            raw_text=raw_text,
            current_input=current_input,
            recent_context=recent_context,
            max_candidate_chars=max(12, min(24, per_seed_max_tokens * 2)),
        )
        ...
    return {
        "candidates": candidates[: max(1, int(max_candidates))],
        "candidateMode": "seeded-prompt-replay",
        "timing": {"branches": branch_timings, ...},
    }
```

Current PR-4 reality:

- `seededPromptReplay=true`, `kvFork=false`, `sequenceFork=false` are exposed in
  predictor health.
- The branch count is capped at top-3 seed tokens.
- Each branch is prompt replay, not true KV-cache fork.
- `candidateMode: "seeded-prompt-replay"` is already test-covered.
- True KV fork is still future work; keep `sequenceFork=false` until there is a
  real cache-copy branch implementation.

### Current RAG retrieval entry point

File: `rag_ime/local_sqlite_core.py`

```python
def suggest_for_input(
    self,
    *,
    current_input: str,
    recent_context: str = "",
    project: str = "",
    app: str = "",
    top_k: int = 5,
) -> list[InputSuggestion]:
    cache_key = self._suggestion_cache_key(
        current_input=current_input,
        recent_context=recent_context,
        project=project,
        app=app,
        top_k=top_k,
    )
    cached = self._get_cached_suggestions(cache_key)
    if cached is not None:
        return cached
    memories = self.retrieve_memories(
        current_input=current_input,
        recent_context=recent_context,
        project=project,
        app=app,
        top_k=max(top_k * 4, 20),
    )
    ranked = [RankedMemory(memory=memory, score=memory.score, rank=index) for index, memory in enumerate(memories, start=1)]
    suggestions = self.compiler.compile(ranked)[:top_k]
    self._store_cached_suggestions(cache_key, suggestions)
    return _copy_suggestions(suggestions)
```

This is the PR-5 insertion point for anti-echo governance: raw input log should
not directly become production candidates; stable memory, lexicon boost,
tombstone, skipped/cooldown, and raw echo penalties should act before
`compiler.compile(...)` returns visible suggestions.

Current memory-v2 gate now does the same suppression/tombstone check before a
candidate becomes visible:

```python
tag_rows = self._memory_item_rows_by_ids(
    conn,
    memory_item_ids=tuple(tag_scores.keys()),
    project=context.project,
    app=context.app,
    limit=max(context.top_k * 4, 12),
)
for row in _merge_rows(phrase_rows, general_rows, tag_rows):
    memory_id = str(row["memory_id"])
    normalized_text = _optimizer_norm(str(row["normalized_text"] or row["text"] or ""))
    source_event_id = int(row["source_event_id"] or 0)
    if self._memory_item_tombstoned(
        conn,
        memory_id=memory_id,
        normalized_text=normalized_text,
        source_event_id=source_event_id,
    ):
        filtered["tombstone"] += 1
        continue
    if self._memory_item_suppressed(
        conn,
        memory_id=memory_id,
        normalized_text=normalized_text,
        source_event_id=source_event_id,
    ):
        filtered["suppressed"] += 1
        continue
    ...
```

And manual phrase tombstones now also tombstone sibling rows by source event or
normalized text:

```python
if normalized_target_type == "memory_id":
    row = conn.execute(
        """
        SELECT normalized_text, source_event_id
        FROM memory_items
        WHERE memory_id = ?
        LIMIT 1
        """,
        (normalized_target_value,),
    ).fetchone()
    conn.execute(
        "UPDATE memory_items SET status = 'tombstoned', updated_at_ms = ? WHERE memory_id = ?",
        (created_at_ms, normalized_target_value),
    )
    ...
    if len(related_clauses) > 1:
        conn.execute(
            f'''
            UPDATE memory_items
            SET status = 'tombstoned', updated_at_ms = ?
            WHERE {' OR '.join(related_clauses)}
            ''',
            related_params,
        )
```

### PR-9 model matrix product metrics

File: `rag_ime/cli.py`

```python
if args.command in {"eval-model-matrix", "model-matrix-eval"}:
    cases = load_eval_cases(Path(args.cases_file))
    models = _parse_model_matrix_models(args.models)
    reports = []
    for model in models:
        matrix_provider = _prediction_provider_for_model_matrix(args=args, model=model)
        model_report = _eval_prediction_provider_on_cases(
            provider=matrix_provider,
            core=core,
            cases=cases,
            project=args.project,
            max_candidates=max(1, min(10, args.max_candidates)),
            match=args.match,
            repeat=max(1, args.repeat),
            latency_budget_ms=max(1, args.latency_budget_ms),
        )
        model_report["model"] = model
        ...
```

Each model row keeps legacy `metrics` and now also emits `productMetrics`:

```python
return {
    "top1Acceptability": ...,
    "top3Coverage": ...,
    "MRR": ...,
    "noiseRate": ...,
    "forbiddenRate": ...,
    "oldInputEchoRate": ...,
    "duplicateRate": ...,
    "avgCandidateChars": ...,
    "firstCandidateMs": _latency_percentiles(first_candidate_ms_values),
    "threeCandidatesMs": _latency_percentiles(three_candidate_ms_values),
    "chainSuccessRate": ...,
}
```

### PR-9 source-aware reranker

File: `rag_ime/reranker.py`

```python
def rerank_candidate_dicts(
    candidates: list[Mapping[str, Any]],
    *,
    query: str = "",
    recent_context: str = "",
    max_candidates: int = 10,
) -> list[dict[str, Any]]:
    """Rank mixed Rime/model/RAG/memory candidates while preserving Rime fallback."""

    scored: list[dict[str, Any]] = []
    seen_texts: set[str] = set()
    query_norm = _norm(query)
    context_norm = _norm(recent_context)
    for original_rank, candidate in enumerate(candidates, start=1):
        text = compact_whitespace(str(candidate.get("text") or candidate.get("surface") or ""))
        ...
        old_input_echo = _is_old_input_echo(text, query_norm=query_norm, context_norm=context_norm)
        score, breakdown = _score_candidate(...)
        scored.append({...})

    ranked = sorted(scored, key=lambda item: (-float(item["score"]), int(item["originalRank"])))
    limited = ranked[: max(1, max_candidates)]
    _ensure_rime_fallback(scored=scored, limited=limited, max_candidates=max(1, max_candidates))
    ...
```

Important behavior: the reranker can promote model/RAG/memory candidates, but it
must preserve at least one Rime fallback when Rime candidates are present.

### PR-10 management API and redaction

File: `rag_ime/debug_server.py`

```python
def management_history(self, payload: dict[str, Any]) -> dict[str, object]:
    report = self.core.list_memory_events(...)
    include_text = self._include_raw_text()
    items = [
        _redact_history_item(item, include_text=include_text)
        for item in report.get("items", [])
        if isinstance(item, dict)
    ]
    return {
        "schemaVersion": "rag-ime.management-history.v1",
        "ok": True,
        "rawTextVisible": include_text,
        "items": items,
        ...
    }


def _include_raw_text(self) -> bool:
    return bool(
        self.config.include_raw_text
        or os.environ.get("RAG_IME_TRACE_INCLUDE_TEXT") == "1"
        or os.environ.get("RAG_IME_DEBUG_INCLUDE_TEXT") == "1"
    )
```

Mutating management actions write an audit row:

```python
def _record_management_audit(...):
    safe_payload = _redact_mapping(payload, include_text=False)
    safe_result = _redact_mapping(result, include_text=False)
    with self.core._connect() as conn:
        _ensure_management_audit_schema(conn)
        cur = conn.execute(
            """
            INSERT INTO management_audit_log(
                created_at_ms, action, target_type, target_id, payload_json, result_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (...),
        )
        return int(cur.lastrowid)
```

The browser management panel lives in `debug/index.html`, `debug/app.js`, and
`debug/styles.css`. It uses one compact side-panel card with five views:
Candidate Explain, History, Memory, Lexicon, and Cleanup.

## Current Verification Snapshot

Recent public-prep verification:

```bash
python3 -m unittest discover -s tests
```

Result:

```text
Ran 491 tests in 78.099s
OK
```

Additional verification after the PR-5 governance/cleanup checkpoint:

```bash
python3 -W error::ResourceWarning -m unittest discover -s tests
```

That full suite also passes, so the earlier SQLite test-connection leakage has
been cleaned up and the current PR-5 governance plus PR-6 cleanup-pipeline
follow-up are covered in the same full run.

Additional narrow PR-4 verification:

```bash
python3 -m unittest tests.test_mlx_predictor_server tests.test_predictor
python3 -m py_compile rag_ime/mlx_predictor_server.py rag_ime/predictor.py rag_ime/cli.py
```

Additional PR-9 verification after adding model matrix product metrics and the
source-aware reranker:

```bash
python3 -m unittest tests.test_model_matrix_eval tests.test_reranker tests.test_predictor
python3 -m unittest tests.test_memory_eval tests.test_memory_optimizer_context_frame tests.test_memory_optimizer_query_plan tests.test_memory_optimizer_sidecar_integration tests.test_prediction_first tests.test_rime_sidecar tests.test_adapter tests.test_model_matrix_eval tests.test_reranker
python3 -W error::ResourceWarning -m unittest discover -s tests
```

Latest full-suite result:

```text
Ran 506 tests in 77.756s
OK
```

Additional PR-10 management API verification:

```bash
python3 -m unittest tests.test_debug_management_api tests.test_debug_server tests.test_memory_optimizer_sidecar_integration
node --check debug/app.js
python3 -m py_compile rag_ime/debug_server.py
```

Targeted result:

```text
Ran 54 tests in 8.901s
OK
```

Latest full-suite result after PR-10:

```text
Ran 514 tests in 74.169s
OK
```

Additional final-gate verification after adding the integrated product gate:

```bash
python3 -m unittest tests.test_product_readiness_gate
python3 -m unittest tests.test_memory_optimizer_sidecar_integration
python3 -m py_compile rag_ime/cli.py rag_ime/rime_sidecar.py scripts/check_squirrel_soak_report.py
```

Product gate targeted result:

```text
Ran 5 tests in 2.649s
OK
```

Backend product gate command now verified:

```bash
scripts/run_product_readiness_gate.sh --skip-unit-tests --skip-acceptance
```

Observed gate result:

```text
rag-pass-rate: 1.0
rime-sidecar-pass-rate: 1.0
rime-sidecar-noise-rate: 0.0
suggestion-cache-warm-hit: true
rime-cache-warm-hit: true
```

Latest full-suite result after the final-gate/fail-closed checkpoint:

```text
Ran 525 tests in 86.582s
OK
```

Recent project-public cleanup:

- Added root `AGENTS.md`.
- Updated `README.md` with public reviewer/pro-model start path.
- Expanded `.gitignore` for `.env*`, SQLite, logs, model weights, archives, and
  build outputs.
- Corrected `docs/runtime-and-debug.md` local MLX example to
  `RAG_IME_PREDICTOR_STREAM_FIRST=0` for multi-candidate behavior.
- Sensitive scan found no real API keys in active files. Tests contain fake
  fixture strings like `secret-value`.

Earlier runtime repair evidence:

- Selected input source:
  `im.rag-ime.inputmethod.RagIme.Hans`.
- Installed app:
  `~/Library/Input Methods/RAG-IME.app`.
- Sidecar:
  `http://127.0.0.1:8766`.
- MLX predictor:
  `http://127.0.0.1:8767`.
- Strict doctor previously passed with `failures=0 warnings=0`.
- Duplicate stale input method bundle was quarantined outside `Input Methods`.
- RAG DB cleanup hid 3 one-off polluted side-candidate rows, removed 3 hidden
  vectors, rebuilt 3990 local-hash vectors, and dry-run then returned
  `matchedNoise: 0`.
- Deployed sidecar verification returned 4 local model candidates and 2 RAG
  candidates for `我想设计一个候选展示方式`.

Treat this as strong but not final evidence. Final acceptance still requires
real foreground typing.

## Commands For A Fresh Reviewer

Basic code verification:

```bash
python3 -m unittest discover -s tests
git diff --check
```

Initialize local demo DB:

```bash
python3 -m rag_ime.cli init-db
python3 -m rag_ime.cli seed-demo --reset
```

Run sidecar directly:

```bash
python3 -m rag_ime.cli sidecar-server --host 127.0.0.1 --port 8766
```

Run local MLX predictor directly:

```bash
python3 -m rag_ime.cli mlx-predictor-server \
  --model "/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-text-4bit-local" \
  --host 127.0.0.1 \
  --port 8767 \
  --prompt-cache
```

Configure sidecar for local MLX:

```bash
export RAG_IME_PREDICTOR_PROVIDER=mlx
export RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:8767
export RAG_IME_PREDICTOR_MODEL="/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-text-4bit-local"
export RAG_IME_PREDICTOR_PROFILE=instant
export RAG_IME_PREDICTOR_STREAM_FIRST=0
```

Restart local runtime:

```bash
scripts/restart_rag_ime_runtime.sh
```

Prepare and build patched Squirrel:

```bash
scripts/prepare_squirrel_workspace.sh
scripts/build_patched_squirrel.sh list
scripts/build_patched_squirrel.sh
scripts/build_patched_squirrel.sh install
```

Doctor:

```bash
scripts/doctor_squirrel_integration.sh
RAG_IME_DOCTOR_REQUIRE_TRYOUT=1 scripts/doctor_squirrel_integration.sh
scripts/wait_squirrel_typing_ready.sh
scripts/verify_squirrel_foreground_trace.sh
```

Foreground trace:

```bash
tail -f "$HOME/Library/Logs/RagIme/squirrel-frontend.jsonl"
scripts/check_squirrel_frontend_trace.py "$HOME/Library/Logs/RagIme/squirrel-frontend.jsonl"
```

x1top offline optimization only:

```bash
cat > ~/.rag-ime-x1api.env <<'EOF'
X1API_BASE_URL=https://x1api.top/v1
X1API_API_KEY=replace-with-your-key
X1API_MODEL=replace-with-your-model
RAG_IME_AI_WIRE_API=chat_completions
EOF

RAG_IME_MODEL_ENV=~/.rag-ime-x1api.env \
python3 -m rag_ime.cli optimize-core \
  --db-path "$HOME/Library/Application Support/RagIme/rag-ime.sqlite" \
  --embedding-provider local-hash \
  --project wisdom-weasel-rag-ime \
  --dry-run
```

Review JSON output before removing `--dry-run`.

## Known Unfinished Work

### 1. Real foreground loop is not fully proven

The backend and doctor are healthy, but the user cares about the real input
panel. Automation can miss macOS focus/Accessibility state, so manual typing
remains important.

Acceptance scenario:

```text
Select RAG-IME - Simplified
Type a Chinese context in TextEdit/Codex/browser
Observe LLM/RAG/Rime source lanes
Press 1/2/3 and confirm candidate commits instead of digit insertion
Select one LLM candidate and wait briefly
Observe next prediction panel
Backspace/Delete text
Confirm next sidecar request uses the deleted-current context
```

### 2. Local seeded top-3 replay exists; true KV fork is still pending

Current MLX path now exposes `seededPromptReplay=true`, `kvFork=false`, and
`sequenceFork=false`. It can take top next-token seeds, replay each seed against
the prepared prompt, and return multiple phrase candidates in
`candidate_mode=seeded-prompt-replay`.

Still missing:

```text
true KV/cache fork
-> no repeated prompt replay per seed
-> better latency under continuous no-input prediction
-> better model-quality filtering/reranking for generic local 0.8B outputs
```

This remains important because the local 0.8B model still produces generic
filler in some contexts even though it is now real local MLX output.

### 3. Source colors have a first product pass, but need real foreground QA

The payload now carries explicit source visuals: `badge` and `colorToken`.
Current mapping is `model=模/modelBlue`, `rag=查/ragTeal`,
`memory=忆/memoryPurple`, `rime=词/rimeOrange`, and
`raw_english=input/rawGray`. Squirrel patch trace summaries include these fields
and `scripts/check_squirrel_frontend_trace.py` rejects mismatched source visuals.

Still missing: manual real Squirrel foreground confirmation that the colors and
badges are visually low-distraction in the actual candidate bar after patch
install, not only in JSON trace and patch tests.

### 4. RAG database cleanup is only conservative so far

Some stale generated/complaint rows were filtered or hidden, but full `x1top`
offline cleanup is still pending:

- the PR-6 CLI path now exists, and strong source-event matches now backfill
  `evidenceEventIds`, but weaker abstract summaries can still fail strict
  validation until evidence linking becomes smarter;
- summarize noisy history into stable memory facts;
- deduplicate similar old inputs;
- extract high-frequency phrases;
- downrank stale generated side candidates;
- provide reviewable cleanup suggestions.

### 5. Model quality is still weak

The current local 0.8B 4-bit model is usable for testing but often low quality.
Next steps:

- compare local models with fixed IME cases;
- measure first useful candidate latency and Hit@1/Hit@3;
- improve candidate filtering and branch generation;
- optionally train/LoRA/rerank after collecting real logs:
  `context -> shown candidates -> accepted/skipped -> next user text`.

### 6. Fuzzy pinyin has PR-8 scripts, but still needs real Rime confirmation

PR-8 now has machine-readable scripts:

```bash
scripts/check_sichuan_fuzzy_profile.sh
scripts/apply_sichuan_fuzzy_profile.sh --dry-run
scripts/apply_sichuan_fuzzy_profile.sh --apply
```

Default mild profile enables `z_zh`, `c_ch`, `s_sh`, `en_eng`, and `in_ing`.
It intentionally keeps `n_l` and `f_h` disabled by default. The remaining check
is real Rime/Squirrel confirmation after applying the profile and rebuilding
user data.

### 7. Visual management UI v1 exists, but is not a large backend

The debug server now has a first localhost-only management panel and API for
candidate explain, redacted history audit, stable memory review, lexicon review,
and cleanup diff review. It is intentionally a small debug-server surface, not
a polished OpenLess-style management application.

Remaining polish:

- per-row selection and explicit second confirmation in the browser UI;
- richer edit/merge flows for stable memories and lexicon phrases;
- export to Rime user dictionary;
- more visual grouping and pagination for large local databases.

## Suggested Next Engineering Plan

### Step 1: Prove foreground continuity

Goal: produce one clean single-session trace proving:

- panel displays model/RAG/Rime source lanes;
- number key selects a visible side candidate;
- selection commits text;
- follow-up prediction appears;
- Backspace/Delete resyncs context;
- stale responses are dropped.

Files likely involved:

- `squirrel-patches/0001-add-rag-ime-sidecar.patch`
- `scripts/verify_squirrel_foreground_trace.sh`
- `scripts/check_squirrel_frontend_trace.py`
- `tests/test_squirrel_frontend_trace.py`

### Step 2: Upgrade seeded replay toward true KV fork and better model quality

Goal: keep the existing `seeded-prompt-replay` multi-candidate path, then make
it faster and smarter with true KV/cache fork if MLX-LM exposes a practical API,
or with stronger local reranking/model matrix selection if cache fork is not yet
available.

Likely target:

- `rag_ime/mlx_predictor_server.py`
- `tests/test_mlx_predictor_server.py`
- `tests/test_doctor_squirrel_integration.py`

Proposed API shape:

```python
def predict_top_seed_continuation_branches(
    *,
    current_input: str,
    recent_context: str,
    max_candidates: int = 3,
    branch_count: int = 3,
    branch_max_tokens: int = 12,
) -> dict[str, Any]:
    ...
```

Implementation sketch:

```text
1. Build prompt from actual context.
2. Run generate_step(..., max_tokens=1) without sampler to obtain logprobs.
3. Pick top N token IDs after filtering obvious low-value tokens.
4. For each seed token:
   a. create prompt or token sequence including the seed;
   b. continue generation for branch_max_tokens with low temperature/top_p;
   c. decode seed + generated continuation;
   d. parse into phrase candidate;
   e. filter echo/meta/filler/repeated context.
5. Deduplicate candidates.
6. Attach candidateScores with seed token ID, logprob/probability, branch rank,
   mode="top-seed-continuation-branches".
7. Return fallback to existing continuation-branches if no branch quality passes.
```

Do not route `x1top` into this path.

### Step 3: RAG offline cleanup pass

Goal: make RAG memory useful instead of old-input repetition.

Likely target:

- `rag_ime/local_sqlite_core.py`
- `rag_ime/memory_generator.py`
- `rag_ime/debug_server.py`
- `tests/test_local_sqlite_core.py`
- `tests/test_memory_generator.py`
- `tests/test_debug_server.py`

Requirements:

- dry-run by default;
- no secrets retained;
- generated side candidates require repeated evidence before becoming strong
  RAG;
- user can inspect cleanup suggestions.

### Step 4: Final source-lane visual polish

Goal: real foreground panel visibly separates LLM/RAG/Rime.

Likely target:

- `squirrel-patches/0001-add-rag-ime-sidecar.patch`
- maybe Squirrel candidate rendering comments/layout methods;
- `macos/RagImeMac/Sources/RagCandidatePanel.swift` only as a visual reference,
  not as the product route.

Acceptance:

- screenshots or trace summaries prove source lane counts and selected item.

## Test Inventory

Important test files:

- `tests/test_mlx_predictor_server.py`: local model generation/candidate modes.
- `tests/test_rime_sidecar.py`: sidecar candidate merge and context behavior.
- `tests/test_doctor_squirrel_integration.py`: doctor/MLX/Squirrel integration
  payload validation.
- `tests/test_squirrel_frontend_trace.py`: frontend trace parsing and session
  assertions.
- `tests/test_local_sqlite_core.py`: RAG/memory ranking, cleanup, feedback.
- `tests/test_memory_generator.py`: `x1top` / `x1api-compatible` offline memory
  generation.
- `tests/test_predictor.py`: predictor config boundaries and candidate parsing.
- `tests/test_prediction_first.py`: source-lane merge.
- `tests/test_debug_management_api.py`: PR-10 management API, redaction, audit,
  and cleanup diff review.
- `tests/test_product_readiness_gate.py`: final product gate script, CLI flag,
  dry-run, and optional macOS foreground-gate coverage.
- `tests/test_install_squirrel_rag_config.py`: Rime/Squirrel config install.
- `tests/test_check_macos_input_source.py`: macOS input source checking.

Run:

```bash
python3 -m unittest discover -s tests
```

## Public/Safety Notes

Do not commit:

- `.env` files;
- API keys;
- local SQLite databases;
- model weights;
- built `.app` bundles;
- personal input history;
- logs containing private input text.

Ignored patterns include `.rag-ime-data/`, `.env*`, `*.sqlite`, `*.db`,
`*.safetensors`, `*.gguf`, `*.mlmodel`, `*.log`, archives, and build outputs.

The repository currently has no final production license decision. Choose a
license before inviting broad reuse beyond analysis.

## What The Pro Model Should Return

Useful answer format:

1. Identify the highest-confidence root cause or missing implementation for the
   current remaining problem.
2. Point to exact files/functions to change.
3. Give a minimal patch plan.
4. Preserve the realtime-local-model and `x1top`-offline boundary.
5. Include verification commands and real foreground acceptance evidence.

The best next code contribution is likely either:

- a robust foreground trace/verification improvement proving continuous
  selection, or
- `MlxLmEngine` top-3 seed continuation branching with tests.

Do not spend the next iteration adding more scattered docs. Keep this file and
`docs/project-status.md` updated instead.
