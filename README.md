# 澄 — Personal Agent Workbench

> A local-first macOS workspace for persistent agents, Rooms, tools, governed
> memory, and optional input, voice, and browser assistance.

**Platform:** macOS 14+ | **Python:** 3.12+ | **License:** [GPL-3.0-only](LICENSE) | **Status:** public-source local prototype

Personal Agent Workbench combines private Agent Sessions, structured
multi-Agent Rooms, auditable Tool and Skill execution, Provider adapters,
governed local memory, and a native Control Center. `澄` is the user-facing
assistant identity. Input-method, voice, and browser integrations are optional
interaction surfaces around the same Agent runtime rather than the center of
the product.

The input path remains deliberately conservative: ordinary Pinyin composition
is still Rime's job, and remote generation is never used for passive
per-keystroke prediction.

> [!WARNING]
> The tracked source repository can be audited and built locally, but the
> project does **not** yet publish a release-ready macOS binary. Foreground
> input/voice/Accessibility acceptance, Developer ID signing, notarization,
> stapling, and the final release manifest remain open. Treat local builds as
> development installations.

## What It Does

| Capability | Current boundary |
| --- | --- |
| Agent Sessions and Providers | Each companion keeps a private, resumable Session with an optional phased Todo that the Agent updates as work advances. Todo tracks progress but grants no execution authority; Pi adapters normalize configured Providers and models without exposing one protocol's private implementation to another. |
| Structured Rooms | A Room starts as normal chronological chat with one default/opening-`@` Facilitator. A stage-resident alignment Skill asks one material question at a time only when needed; a complete request starts without an extra confirmation. `room_define` fences intake and the Kernel creates a new implementation Dispatch with the execution Skill. Peer Room companions may own parallel WorkItems and each may use bounded private subagents shown under its task. Integration, policy-selected independent review, receipts, one ReportDispatch, and one facilitator final remain backend-governed. |
| Tools and Skills | Tools are progressively disclosed, policy-checked, approval-aware, and recorded as typed receipts. Skills are loaded for the current work stage instead of being dumped into every prompt. |
| Control Center | The native macOS workspace exposes conversations, projects, companions, memory, knowledge, planning, diagnostics, Provider settings, and bounded context inspection. |
| Governed memory | SQLite evidence, Atoms, Books, tags, projections, revision fences, and retrieval keep long-term context reviewable and reversible rather than silently rewriting chat history. |
| Optional interaction adapters | Patched Squirrel, push-to-talk voice, and Browser Co-pilot feed the same local workspace without owning Agent or memory semantics. |
| Pinyin composition | Rime/librime owns schemas, fuzzy Pinyin, paging, native candidates, and user-dictionary ranking. The sidecar must never replace its composition path. |
| Local completion | After a commit, a local MLX, Ollama, or loopback OpenAI-compatible runtime may offer short, source-marked continuations. `Tab` accepts the first suggestion and `Option+number` selects an ordinal; ordinary number keys stay with Rime or the host. |
| Explicit knowledge work | Selected-text assistance, long-form answers, memory organization, and configured remote generation are explicit Control Center workflows, not background typing behavior. |

## System Capabilities

The status labels below deliberately distinguish code presence from real macOS
foreground acceptance. "Implemented" does not mean that signing, notarization,
or every host application's text field has passed manual testing.

### Agent Workspace And Control Center

**Status: implemented for local development; signed distribution remains a
separate gate.**

The native Control Center is the composition surface for Agent Sessions,
Provider-qualified model selection, project-grouped conversations, companions,
Rooms, memory, knowledge, planning, voice, input assistance, and diagnostics.
Session history remains private; Room posts, Task handoffs, approval receipts,
and accepted evidence are projected into shared collaboration state. Managed
file and Diff results expand inline so the work stays in context instead of
opening an unrelated modal workflow.

### Rime Input

**Status: implemented; real foreground acceptance remains required.**

The optional input frontend is a single patched Squirrel/InputMethodKit route.
Rime continues to own Pinyin parsing, fuzzy Pinyin, paging, native candidates,
and the user dictionary. 澄 adds a source-aware assistant surface rather than
replacing Rime's decoder. Ordinary number keys stay with Rime/the host; `Tab`
and `Option+number` select assistant candidates. The Control Center can set
post-commit enablement, trigger/cooldown limits, candidate count, Tab policy,
and Option+number policy. Candidate count and trigger delay are projected only
into the application-owned Rime YAML block before an attended Squirrel reload;
user dictionaries and user-owned YAML remain outside that write boundary.

### Local LLM Prediction

**Status: in development; runtime integration and automated tests are present,
but candidate quality and foreground stability are still release gates.**

Passive post-commit prediction uses a local runtime such as MLX, Ollama, or a
loopback OpenAI-compatible server. It emits short continuations without sending
every keystroke to a remote model. The final prompt prioritizes the live input,
today's plan, complete recent inputs, and then budgeted RAG evidence; it asks for
bare continuation instead of an explanation or a copy of retrieved text.

The Control Center input page exposes the governed local-prediction settings:
registered hot model, local path, runtime profile, prompt mode, token cap,
sampling values, and post-commit latency budget. Saving records desired state;
the installed native host must then run the fixed `restart_predictor` action,
which updates the model registry, reinstalls MLX and Sidecar, and accepts the
change only after both health payloads agree. A browser build can edit through
the approved settings contract but cannot execute this local helper.

Current development-machine timing is split into two different measurements:

| Measurement | Current observation |
| --- | ---: |
| Prefill / first token | about **54 ms** |
| Three complete candidates | about **206 ms** |

These are one local development measurement, not a service-level guarantee.
Hardware, model, quantization, cache state, input length, and runtime all affect
the result. In particular, this README does **not** claim that prediction is
"finished in 50 ms".

### Hybrid RAG

**Status: implemented in the local core and sidecar; foreground relevance still
needs continued evaluation.**

Retrieval combines SQLite FTS5 BM25, vector similarity, tags and tag relations,
time, feedback, and weighted reciprocal-rank fusion. A configurable soft
context budget defaults to 4096 tokens with 1024 tokens reserved for output.
Each consumer owns a bounded projection instead of receiving one shared text
dump. Explicit generation prioritizes the current field, up to six planning
items, two approved Timeline tasks, four recent complete inputs, and six
governed Atom/Book grounding items. A new Agent Session receives one compact
bootstrap; later turns rely on Session history and on-demand `memory` calls.
Diagnostics report the number and estimated tokens actually injected for each
source.

Explicit queries such as "yesterday", "last week", "before", or "the original
requirement" can retrieve the corresponding time window and bypass ordinary
age decay. Old material is preserved, not silently treated as current truth.

### AI Memory

**Status: in development; draft generation, replacement links, decay, and
rollback contracts are implemented and await prolonged real-data validation.**

Short one- or two-character commits do not automatically become facts. Nearby
Rime fragments are assembled using punctuation, pauses, focus changes, and
context groups before they receive normal memory weight. New explicit facts,
preferences, decisions, and requirements may supersede older memory without
deleting its source. Temporary plans decay quickly, project state decays at a
medium rate, and stable preferences decay slowly.

Memory curation starts from an immutable evidence ledger rather than from the
retrieval index. Eligible evidence is limited to final user input, explicit
remember actions, applied tool receipts, and role-session compaction summaries.
Generated side candidates, assistant turns, screenshots, fixtures, and model
output are not memory sources. Once per day, each user, shared scope, or role is
curated independently within its project. Deterministic noise rules run first;
the configured organizer classifies the rest and can only create a review
draft. Apply and rollback move every covered source together, including all
low-level commits reconstructed into one Rime utterance.

Forgetting is a reversible evidence disposition, not source deletion. Restoring
rewinds the owner cursor so the evidence is classified again. Automatically
excluded sensitive input remains non-restorable; create a separate, redacted
explicit memory instead.

The maintenance runner uses this owner-scoped path by default. The previous
global compiler is retained only for compatibility and requires
`RAG_IME_LEGACY_MEMORY_BOOK_MAINTENANCE=1`.

### Personal Knowledge Base

**Status: in development; local review workflow is implemented.**

The knowledge workbench combines local memory with optional explicit knowledge
generation. AI organization produces an editable draft first. Only an explicit
review action applies selected changes to formal memory, indexes, or the Rime
lexicon. It is not a background remote upload path.

### Document Knowledge Libraries

**Status: in development; document management, parsing, indexing, retrieval,
source review, and an independent document graph are implemented.**

Large external documents live in a separate Knowledge Worker domain rather
than being mixed into personal memory. The Control Center manages libraries,
imports, parser and chunking settings, retrieval settings, source/Markdown/
chunk/asset review, index jobs, retrieval tests, and a document knowledge
graph. Built-in parsing is always available; MinerU can be installed as an
optional local parser for layout-heavy PDFs and OCR. The graph projects
document structure, topics, entities, terms, and evidence-bearing chunks into
its own SQLite tables, with source navigation and rebuild status, without
touching the personal-memory relationship graph.

Agent access remains one explicit, read-only `knowledge` tool. The graph is
currently a Knowledge Worker retrieval and control-plane feature, not a second
agent tool, so graph expansion cannot silently increase the agent's authority.

### Memory And Knowledge Management

**Status: in development; management APIs and native views are implemented.**

The Control Center can inspect full content, source events, tags, relationships,
timestamps, confidence, and supersession state. Management operations include
edit, merge, archive, suppress, restore, and rollback. Tag exploration supports
both a list and a relationship graph. Topic books are reused instead of being
created after every organization run; after a configurable inactive period
(60 days by default) they become archive candidates. Archived books remain
searchable with lower ordinary weight and can reactivate when an old project is
explicitly requested or relevant content appears again.

### Voice Input

**Status: in development; recording, streaming ASR, overlay, and insertion are
implemented, while host-specific focus behavior still requires manual tests.**

The optional `RagImeVoice.app` agent shows a foreground recording overlay and
an audio-reactive waveform, streams speech to the configured ASR provider, and
inserts the final text at the active cursor. It runs outside Squirrel's
keystroke path so a microphone/network failure cannot block ordinary typing.
Microphone and Accessibility permissions belong to the stable installed app,
not a temporary derived-build identity.

### Daily Planning And Assistant

**Status: in development; database, API, context injection, completion-event
recognition, undo, and the native page are implemented.**

The Planning page keeps long-term goals, today's plan, prioritized Todos,
deadlines, completion state, and daily notes together. The assistant summarizes
what was completed, what remains, and a sensible next action. Explicit phrases
such as "completed task X" can complete a matching Todo and provide undo;
ambiguous language only creates a confirmation suggestion. Open tasks, goals,
and daily notes are eligible for the model context under the shared token
budget.

### Structured Agent Rooms

**Status: core source paths are implemented; the conversation-first lifecycle and
current managed-Pi payload still require fresh installed foreground acceptance.**

Rooms support two explicit kinds: project collaboration and roleplay chat.
They share one event contract, but keep different authority boundaries:
collaboration Rooms require an authorized workspace, while roleplay Rooms can
run without filesystem access. Routing is stored as structured configuration
(`manual_mentions`, `moderator`, `sequential`, `natural`, or `invite_only`);
participants are recorded by stable ID rather than by inserting fake speaker
prefixes into message text.
Choose the tier that matches the accountability you want:

- **Facilitator/reporter:** coordinates the Room, settles requirements, assigns and integrates work, decides whether independent review is needed, and owns the one final user-facing report. In a Room this is the only user-question owner: material questions go through `room_commit(wait)`; native Ask is reserved for a standalone parent Session outside a Room.
- **Room partner Session:** a durable participant with a collaboration role and an accountable WorkItem/Dispatch. Choose a partner when the work needs a public Room responsibility, directed reassignment or cancellation, and an evidence-backed handoff. Multiple partners may run in parallel only for genuinely independent, non-overlapping slices; dependent work stays serial. Progress, accepted evidence, and handoffs may be public; the participant's transcript and reasoning remain private.
- **Nested subagent:** a bounded private child Session for a narrow research, planning, or implementation check. It is not a Room member, cannot own or settle a Room Root/Task, and cannot publish its private transcript. It returns a bounded result to its parent as evidence; the parent must verify and integrate it rather than treating the return as automatic acceptance. The parent or Kernel may cancel it, and late output cannot revive cancelled work.

Use a Room partner for durable, publicly accountable collaboration; use a nested
subagent when the parent only needs a private, bounded result. A Room partner
may launch a bounded nested batch for a smaller check; batch size and depth
stay within the managed limits, while the selected role/profile determines
read-only versus Worker capabilities.

#### Context, questions, and workspace tools

For a nested run, choose `fresh` for an independent review or other task that
does not need the parent's conversation. Choose `fork` only when the parent's
managed Pi transcript prefix materially helps and reusing its cache is worth
the cost. A fork reuses the exact managed prefix and appends the bounded child
brief; it does not reorder system, model, or Tool prompts merely to personalize
the branch. Both modes keep the child Session private.

Room partners and nested children do not open competing native Ask prompts. A
Room partner uses `room_commit(wait)` for its assigned Room work; a nested
child has no Room authority and returns only a structured blocker to its
parent. The Facilitator/Reporter decides whether to publish a Room wait.
Outside a Room, a standalone parent Session may combine one to four independent
material questions into one native Ask; questions with dependencies are asked
separately.

`workspace_lsp` is role- and authorization-scoped. Read-only roles may inspect
status, symbols, hover, definitions, references, and diagnostics. A writable
Worker may request `rename` or `code_action_apply` only through the existing
hash-bound approval path; it must inspect references before changing an
exported symbol. No role gains access to an unauthorized workspace, and a
read-only child profile does not gain write operations.

Managed `agents` delegation accepts one or two tasks per batch and limits
nested delegation to depth two. Each child remains bounded by its run budget
and terminal cancellation state; these limits apply to nested delegation, not
to the number of Room participants or WorkItems.

When a nested batch is Room-bound, its causal metadata links it to the Room
`taskId`. The task read model may show each child beneath that task using only
template, ordinal, task, state, budget, result/error, and timing. Protocol IDs,
private transcript content, and child reasoning are not normal Room graph
content; the Room Kernel still owns lifecycle and settlement.

The three tiers use a conditional conversation-first sequence. `澄·远` is the
default initial Facilitator; one explicit `@` in the opening message may select
another Room companion. Later mentions are communication, not ownership.

The opening user bytes are preserved as an immutable RequirementAnchor and an
explicit-user RequirementItem with its source span. The canonical sequence is:

1. The receiving Facilitator inspects reachable facts under an `align` Dispatch
   whose managed Pi Session requires the stage-resident
   `alignment-and-decision` Skill.
2. If no material user-owned choice is missing, do not ask for confirmation.
   The opening request authorizes definition and execution.
3. If a material choice is missing, `room_commit(wait, waitingFor=user)`
   publishes one structured question at a time. The next ordinary user Room
   message appends an answer revision, publishes the chronological user post,
   and creates one idempotent resume for that `(questionId, answerRevision)`.
   One Root may resume for several different questions.
4. After the final necessary answer, the Facilitator summarizes the aligned
   goal and asks `现在开始行动吗？`. Only that clarification branch requires the
   user's chronological `开始行动` message before execution.
5. `room_define` atomically and idempotently binds the current immutable
   RequirementCatalog revision, objective, requirements, and acceptance
   criteria to the existing Root/Task; creates or confirms one accountable root
   WorkItem; completes/fences the intake Dispatch; and records the transition.
6. The Kernel creates a new execute-capable Facilitator Dispatch with a new
   lease/epoch. Its managed Pi Session requires `implementation-execution`.
   The old align Dispatch never gains execute Tools and cannot resume late.
7. The Facilitator owns decomposition, assignment, reassignment, dependency
   handling, integration, and the final report. Keep a small coherent change
   with one Implementer. Split into multiple child WorkItems only when at least
   two slices are genuinely independent, have no unmet prerequisite, and
   parallel execution materially reduces waiting; do not use round-robin,
   free-text `@` mentions, or extra Agents as an assignment mechanism.
8. Workers act through directed Kernel Dispatches and their bound workspace
   harnesses. Read-only work may share a baseline; concurrent writable work
   must use separately receipted isolated workspaces based on the same Root
   baseline, with one Facilitator-owned integration workspace. Dependent work
   stays serial. A Worker may reject an assignment with a structured reason;
   the Facilitator repairs or reassigns it rather than silently widening scope.
9. Workers return artifacts and evidence to the Facilitator, who integrates the
   accepted results in the authoritative workspace. Only after integration does
   the Facilitator decide whether independent review is warranted. If review is
   chosen, the Kernel hands the existing WorkItem to a distinct Reviewer; the
   Reviewer never reviews its own or the Integrator's work, and a failed review
   returns the WorkItem to the Facilitator for repair. Review is risk-based, not
   mandatory for every task.
10. Required stage Skills change with authoritative Dispatch intent:
    `independent-review` for review, `quality-gate` for close, and
    `structured-handoff` for handoff. The runtime pins Skill hash and
    Root/Task/Dispatch/Session/capability-epoch receipts; a stage change reopens
    the idle managed Pi Session with the new exact Skill.
11. The Kernel validates evidence, terminal receipts, permissions, and work
    quiescence. It then creates one read-only ReportDispatch; only the
    facilitator/reporter emits one final public summary. The reporter receipt
    and runtime quiescence are required before Root completion.

Participant Session/Dispatch ownership is distinct from filesystem roots.
Each participant acts only through its own bound workspace harness and accepted
evidence receipts. A filesystem path does not prove identity or isolation; do
not claim automatic Git worktree cloning without an inspectable receipt.
Private participant reasoning and internal references stay private.
`room_post` is not a second clarification channel; it is for material progress,
not completion or acceptance evidence; a model's prose cannot settle a Root.

Personal Agent Workbench is the Room authority: the Room Kernel, contracts,
durable snapshots/events, and managed Pi Skills define this lifecycle. The
local `clowder-ai` Cat Cafe reference checkout is a
reference-only source of mechanism lessons, not an implementation dependency.
Its thread queue, event/reducer, handoff-recovery, and independent-review
ideas are compared in `ARCHITECTURE.md`; its protocol, IDs, reducer/source,
schemas, and routes are not copied.

After definition and the new ExecuteDispatch, the Room may use `room_collaborate` only for a
bounded, non-overlapping implementation child while the current Facilitator
retains responsibility. It is never an intake fanout, assignment-by-mention,
review child, or replacement for a Kernel handoff. The shared result remains
private until the Facilitator integrates required results and any chosen review
evidence is accepted. Each participant keeps a private Session; only
intentionally public progress, accepted evidence, handoffs, and results enter
the Room timeline.

The **Tasks** view in the Control Center is a dedicated work surface and leads
with a live flow diagram:

```text
Created -> assigned WorkItems -> participant execution -> Facilitator integration
         -> optional independent review -> Kernel settlement -> Reporter summary
```

Every work item gets its own path. Nodes show the responsible companion,
current action, and state; connectors show which paths are waiting, active,
complete, stopped, or need attention. The diagram updates from Room snapshots
and events, stacks into a readable vertical flow in narrow layouts, and uses
icons plus text rather than color alone. Detailed per-participant progress,
review state, receipts, and private-session disclosure remain available below
the diagram without competing with the primary lifecycle.

Each accountable Room companion may also launch bounded private subagents for
its own slice. Those nested runs appear inside/beneath the parent WorkItem with
their public-safe task, state, budget/usage, result/error, and timing. They are
visually subordinate to that parent and never become peer Room companions or
delivery owners. This two-level view distinguishes several peer Room companions,
each with possible private children, from a single-master/many-subagents tree.

The diagram is a read model, not a second task engine. Room lifecycle and
terminal decisions remain owned by the backend. A failed, blocked, cancelled,
or not-yet-final run therefore cannot be painted as a completed shared result
just because a participant returned text.

The same backend ownership applies to causal child work. Nested subagents and
governed `workspace_job` commands are linked to the current
Root/generation/Dispatch; finalization waits for them, and stopping the Root
fans cancellation out to their authoritative owners. The Agent status panel
shows durable background-task state, bounded logs, refresh, and cancel controls.
Hiding `workspace_job` from a later model turn does not hide or orphan a job
that is already running.

Managed Pi preloads only the Room responsibility loop (`room_state`,
`room_post`, and `room_commit`). `room_define`, `room_collaborate`, workspace
Tools, and other product capabilities use the same progressive
`tool_search`/`tool_load` path as ordinary Agent work. A successful load receipt
adds the requested Tool without replacing already available built-ins.

Each Room also owns a versioned common scenario, independent topics, and
workspace-scoped shared artifacts. Topic changes only alter subsequent working
context: participant identity, private Agent memory, global user memory, Room
history, and shared files remain separate objects.

### Session-Scoped Agent Context

**Status: implemented in the local Agent runtime; long-running policy and
review UX validation remain in development.**

Each Agent role has a versioned Role Book containing approved collaboration
style, evidence-backed capabilities, recent work with expiry, lessons, limits,
and commitments. A Session pins one approved revision, so the role cannot
silently change halfway through a conversation. Identity, permissions, safety
rules, tool allowlists, and approval levels remain outside the Role Book.

A new Session receives one query-free, budgeted bootstrap that can contain
stable preferences, current project tasks and goals, active Memory Books and
Atoms, recent cross-application timeline Books, and a small One Ring
conversation tail.
One-shot context is reserved before Runtime dispatch and is not reinjected on a
retry. Later turns use Pi's native Session history; long-term memory is read
only when the Agent explicitly calls `memory` in `current`, `historical`,
or `change` mode.

Chats, applied tool receipts, and accepted Room work are recorded as Evidence,
not facts. Daily maintenance produces a conversation digest plus separate user
memory and Role Book drafts. Explicit remember, correct, forget, and rollback
operations are hash-bound, approval-gated, lineage-aware, and projected
asynchronously through the durable outbox. Cross-application typing activity
continues through the separate `input_events` to daily Memory Book timeline,
so raw dialogue or typing history is never silently promoted into a system
prompt.

The bundled `rag-ime-memory-curator` skill follows the same authority boundary:
Evidence can support a Current Atom, Atoms can be organized into Topic Books,
and cross-App activity can become a reviewed Task Timeline. The skill may
prepare and apply governed memory proposals, but it cannot bypass native
approval or activate a Role Book revision.

### Diagnostics And Repair

**Status: implemented; doctor output is necessary but not sufficient evidence.**

The diagnostics surface separates process health, model readiness, retrieval,
permissions, context capture, and final model injection. It records the exact
source counts and token estimates used by a request, while raw trace text stays
behind an explicit debug option. Repair commands cover the sidecar, launch
agents, patched Squirrel registration, voice agent, and local model runtime.

### Configuration, Backup, And Restore

**Status: in development; YAML preview/apply and portable backup/rollback are
implemented and tested.**

`config/rag-ime.config.example.yaml` documents every importable setting and the
instant, knowledge, and voice provider slots. A user may create the ignored
`config/rag-ime.config.yaml`; import changes it to mode `0600`, previews all
changes, and moves supplied secrets into macOS Keychain without echoing them in
the response. Existing keys are preserved when a slot omits its secret.

A portable backup contains management settings, provider metadata without
secrets, the SQLite database (including memory, knowledge, plans, and Todos),
and safe Rime YAML/dictionary files. It deliberately excludes API keys, access
tokens, model weights, caches, logs/traces, and Rime binary user databases.
Restore validates every manifest entry, previews counts, snapshots current
state, applies migrations, and rolls the database, Rime files, and provider
metadata back if any step fails. The backup itself is not password encrypted.

## Architecture

```text
Pinyin composition
  -> Rime/librime
  -> patched Squirrel
  -> native composition panel and native commit

Post-commit assistance
  -> trusted foreground snapshot
  -> Python sidecar (/rime-suggest)
  -> local completion + local Hybrid RAG / memory
  -> source-aware Squirrel overlay
  -> Tab or Option+number
  -> feedback (/rime-select)

Explicit workflows
  -> RagImeControl.app
  -> local evidence and optional configured remote provider
  -> reviewed result, draft, or explicit insertion

Daily memory curation
  -> immutable final-input / receipt / compaction evidence
  -> owner + project cursor
  -> deterministic noise filter
  -> bounded organizer classification
  -> review draft
  -> apply or rollback
  -> owner-scoped retrieval documents
```

Squirrel is the only real input-method frontend in this repository. The
versioned frontend gateway exists to isolate shared backend contracts, but this
project does not claim a Linux, Fcitx5, IBus, or second InputMethodKit runtime.
`RagImeControl.app` is the supported settings and diagnostics surface;
`RagImeVoice.app` is a headless voice agent rather than a second control center.

## Privacy And Safety

- Passive completion and retrieval are local by default.
- Secure Input, password fields, account-like fields, unknown privacy state,
  and stale focus fail closed before recording, retrieval, or model inference.
- Remote generation is limited to explicit workflows. Selected text or context
  leaves the Mac only after a user-configured action invokes that provider.
- Raw typing history is not silently promoted into searchable memory. Memory
  evidence is classified daily, and semantic organization creates a validated
  draft that the user reviews, applies, or rolls back. Evidence can be forgotten
  and restored without deleting its audit trail.
- Model weights, local databases, personal input history, API keys, build
  artifacts, and machine-local configuration must never be committed.

Review the source and the Web Control Center privacy settings before using
the project with sensitive material.

## Quick Start

### Requirements

- macOS 14 or newer for the native build and foreground verification route.
- Python 3.12 or newer. The source uses PEP 701 f-string syntax that does not
  parse on Python 3.10 or 3.11.
- Xcode command-line tools; full Xcode is required to build patched Squirrel.
- Apple Silicon plus `mlx` / `mlx-lm` only when using the resident MLX
  predictor.
- A separately obtained local model checkpoint. Model weights are not included.

### Run The Core Locally

Run the test suite first:

```bash
python3 -m unittest discover -s tests
```

Initialize a local database and start the sidecar:

```bash
python3 -m rag_ime.cli init-db
python3 -m rag_ime.cli sidecar-server --host 127.0.0.1 --port 8766
```

For a deterministic demonstration that does not touch personal history:

```bash
python3 scripts/ime_first_demo.py seed --reset
python3 scripts/ime_first_demo.py verify --report output/ime-first-demo-report.json
python3 scripts/ime_first_demo.py reset
```

### Build The macOS Frontend

Prepare the pinned Squirrel checkout and build it with the project patch:

```bash
scripts/prepare_squirrel_workspace.sh
scripts/build_patched_squirrel.sh build
```

Build or install the supported Control Center. The same React application runs
inside the minimal WebKit shell on the Mac and as a same-origin HTTP build on
the isolated Agent Gateway:

```bash
scripts/build_control_center.sh
scripts/build_control_center.sh install
```

`build_control_center.sh install` updates only the Control Center app. For an
existing full installation, use the generation-checked stack installer so the
Sidecar, Agent gateway, MLX worker, voice agent, maintenance job, and visible
app cannot silently remain on different commits:

```bash
scripts/build_control_center.sh install-stack --include-squirrel --include-pi
scripts/check_installed_product_components.py --require-current
```

The stack installer isolates each worker's copied Python package, records its
source commit, refuses dirty tracked source by default, and audits the complete
installed generation before returning success.

For the pinned Pi checkout, non-destructive native build walkthrough, local
installation variants, rollback command, and the separate source-public versus
signed-distribution gates, see [Build, Install, And Release](release/README.md).

### Review And Migrate A Legacy Memory Database

Historical curation is manual, copy-first, and fail-closed. Do not let a local
large model rewrite the production database. First export an immutable private
snapshot, make an explicit decision for every logical input and every existing
Atom, Book, and Phrase, and validate the complete manifest. Questions without a
durable assertion, workflow noise, failed receipts, duplicates, and one-turn
commands stay in Evidence/audit storage as `not_for_memory`; they do not become
Atoms, Books, Timelines, Phrases, or retrieval documents.

A production candidate additionally requires the configured embedding provider,
complete document/vector parity, caught-up projection checkpoints, an empty
failed/dead Outbox, and exact source fingerprints. No Timeline or Role Book draft
is auto-approved.

The `wisdom-weasel-rag-ime` value in the migration command below is a legacy
persisted project scope, not the current product name. Existing databases,
schema identifiers, `rag_ime` imports, and `RAG_IME_*` environment variables
retain compatibility until a separately versioned data migration can update
them without losing memory provenance.

```bash
DB="$HOME/Library/Application Support/RagIme/rag-ime.sqlite"
SNAPSHOT="/private/path/rag-ime-reviewed-source.sqlite"
EXPORT="/private/path/rag-ime-review-export.json"
MANIFEST="/private/path/rag-ime-review-manifest.json"
CANDIDATE="/private/path/rag-ime-reviewed-candidate.sqlite"
ROLLBACK="/path/to/rag-ime-before-semantic-v2.sqlite"

python3 scripts/review_memory_history.py export \
  --source "$DB" --snapshot "$SNAPSHOT" --output "$EXPORT" \
  --project wisdom-weasel-rag-ime --timezone Asia/Shanghai

# Review every exported logical input and existing memory item. Then assemble
# the reviewed parts and catalog audit into one complete manifest.
python3 scripts/review_memory_history.py assemble \
  --export "$EXPORT" --part /private/path/review-part-01.json \
  --existing-audit /private/path/existing-memory-audit.json \
  --output "$MANIFEST"
python3 scripts/review_memory_history.py validate \
  --export "$EXPORT" --manifest "$MANIFEST"

python3 scripts/apply_manual_memory_review.py \
  --source "$SNAPSHOT" --export "$EXPORT" --manifest "$MANIFEST" \
  --output "$CANDIDATE" --embedding-from-env

scripts/stop_rag_ime_runtime.sh
python3 scripts/activate_semantic_memory_candidate.py \
  --target "$DB" --candidate "$CANDIDATE" \
  --report "${CANDIDATE}.manual-review-report.json" --rollback "$ROLLBACK" \
  --confirm ACTIVATE_SEMANTIC_MEMORY_V2
scripts/build_control_center.sh install-stack --include-squirrel --include-pi --include-mlx
```

The activation report is bound to the candidate SHA-256 and all four reviewed
source fingerprints. They are revalidated immediately before the atomic
replacement, and the activated database is verified again afterward. Keep all
writers stopped from the final drift check through activation.

### Multi-Device Agent Gateway

The Agent Gateway remains a control-plane process on loopback `127.0.0.1:8768`.
It serves the production HTTP Control Center and the existing REST/SSE API from
one origin. Squirrel and the foreground typing path continue to use the
separate `127.0.0.1:8766` Sidecar; remote devices never enter that hot path.

For local development:

```bash
RAG_IME_CONTROL_TRANSPORT=http \
RAG_IME_CONTROL_BUILD_CHANNEL=production \
  scripts/build_control_center_web.sh
python3 -m rag_ime.cli agent-gateway \
  --host 127.0.0.1 \
  --port 8768 \
  --web-dist control-center-web/dist
```

To expose the already installed gateway to phones, tablets, and other Macs on
the same tailnet:

```bash
scripts/configure_agent_gateway_tailscale.sh enable --login you@example.com
scripts/configure_agent_gateway_tailscale.sh status
scripts/configure_agent_gateway_tailscale.sh disable
```

This route uses tailnet-only Tailscale Serve, never public Funnel. The gateway
accepts remote requests only when Serve supplies an allowlisted
`Tailscale-User-Login`; it then applies the canonical remote-safe route and
scope policy. Provider credentials, plugin installation, arbitrary files,
database apply operations, and input-method configuration remain local-only.
Session prompts and Room messages use durable `clientMessageId` receipts, so a
network retry cannot silently start the same Agent turn twice.

Installing an input method changes user-level macOS state. Use an attended
foreground session and verify the actual UI rather than trusting an HTTP
response:

```bash
scripts/doctor_squirrel_integration.sh
scripts/verify_squirrel_foreground_trace.sh
```

The optional voice lane, Active RAG provider, and Notion Worker each have
separate setup in the Web Control Center; none is required for the local
core.

## Browser Co-pilot

The optional Chrome extension under `integrations/browser-copilot/` adds a
local, auditable browser lane without putting full pages into every Agent
prompt:

- the extension keeps compact multi-frame page snapshots in the existing local
  SQLite control plane;
- `browser` reads snapshots or screenshots on demand and sends write
  actions through the existing Agent approval flow;
- the Control Center exposes browser selection, visual and structured page
  views, site permissions, execution traces, pairing, and an isolated managed
  Chrome profile;
- first-time cross-origin navigation requests a site decision and asks the
  Agent to retry after approval; passwords are never included in snapshots.

The product installer copies the unpacked extension to
`~/Library/Application Support/RagIme/BrowserCopilot/extension`. Load that
directory once from `chrome://extensions` with Developer mode enabled.

## Validation And Release Gates

The project distinguishes backend evidence from real foreground behavior.
Passing tests or a health probe does not prove a visible, selectable candidate
in a foreground application.

```bash
python3 -m compileall -q rag_ime scripts tests
python3 scripts/check_import_boundaries.py
python3 scripts/check_product_status.py --json
python3 scripts/check_public_release.py --allow-blocked
python3 scripts/evaluate_deployed_rime_lexicon.py
python3 -m unittest discover -s tests
```

`check_public_release.py --allow-blocked` is intentionally a report while the
prototype is unfinished. A real release additionally needs a clean source
commit, foreground acceptance, Developer ID signing, notarization, stapling,
and a hash-bound `rag-ime.release-manifest.v2` that verifies the project
`LICENSE`, third-party notices, and exact patched Squirrel corresponding source.
See the [release-manifest template](release/release-manifest.example.json).

## Repository Map

| Path | Purpose |
| --- | --- |
| `rag_ime/` | Python sidecar, local RAG/memory core, model runtime adapters, management API, and release audit. |
| `squirrel-patches/` | Pinned Squirrel patch, Swift overlay, and patch application checks. |
| `control-center-web/` | React settings, diagnostics, knowledge, planning, and Agent UI. |
| `integrations/browser-copilot/` | Local Chrome extension for compact page snapshots, screenshots, approved actions, and site-permission prompts. |
| `macos/RagImeControlWebHost/` | Minimal AppKit/WebKit host and allowlisted native bridge for the Web Control Center. |
| `macos/RagImeVoice/` | Headless push-to-talk agent, microphone pipeline, and cursor insertion. |
| `macos/Shared/` | Shared native Keychain and streaming-ASR protocol code. |
| `scripts/` | Build, install, runtime, evaluation, release, and foreground-verification commands. |
| `tests/` | Unit, contract, privacy, patch, release, and integration-style tests. |
| `eval/` | Synthetic public evaluation fixtures with no personal input history. |
| `release/` | Public-safe feature registry, product status, and release-manifest template. |
| `dataset/` | Public-safe demonstration and regression fixtures, not a production training corpus. |

## Scope And Non-Goals

- This is a local-first personal Agent workbench, not a hosted autonomous
  workforce, enterprise control plane, or general cloud Agent service.
- The native product currently targets macOS. The optional input adapter is a
  Rime/Squirrel experiment, not a general cross-platform IME.
- Rime remains authoritative during Pinyin composition; model and RAG output
  does not reorder native candidates or train the Rime user dictionary.
- Remote models are not permitted in passive per-keystroke completion.
- Room collaboration does not merge private Session histories. Only explicit
  Room posts, evidence, Tasks, handoffs, and receipts become shared state.
- The repository does not redistribute trained model weights, personal typing
  history, or a production-scale training corpus.
- A public source repository and an ad-hoc signed engineering build are not
  proof of a distributable macOS product.

## Contributing

Keep changes narrow, preserve the Rime/Squirrel foreground boundary, and add
tests for behavior, privacy, contracts, or patch application. Do not submit
credentials, personal typing history, local databases, model weights, generated
app bundles, or machine-specific defaults.

Before opening a pull request, run the validation commands above and verify UI
changes through the real Squirrel foreground path, not only preview fixtures.
When a change distributes or packages patched Squirrel, preserve the required
notices and corresponding source.

## License

Unless a file says otherwise, project-authored source is Copyright (C) 2026 7155 and
licensed under [GPL-3.0-only](LICENSE). GPL is a deliberate choice for
this project because its distributable macOS route includes a modified GPL-3.0
Squirrel app.

Third-party code, model weights, datasets, and remote services retain their own
terms. A patched Squirrel binary or source distribution must include the
applicable notices and exact corresponding source; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Acknowledgements

- [Squirrel](https://github.com/rime/squirrel) and
  [librime](https://github.com/rime/librime) provide the macOS frontend and
  Rime engine foundations.
- [Felix3322/Wisdom-Weasel](https://github.com/Felix3322/Wisdom-Weasel)
  informed the prediction lifecycle and candidate-panel direction; its
  implementation source is not copied into this repository without a separate
  provenance review.
- [MiniMind](https://github.com/jingyaogong/minimind),
  [MLX](https://github.com/ml-explore/mlx),
  [Ollama](https://github.com/ollama/ollama), and
  [llama.cpp](https://github.com/ggml-org/llama.cpp) inform or provide optional
  local model runtime boundaries.
- [OpenLess](https://github.com/Open-Less/openless) and
  [LazyTyper](https://github.com/oldcai/LazyTyper-releases) informed the voice
  interaction study. [Volcengine Doubao streaming ASR 2.0](https://docs.volcengine.com/docs/6561/1354869?lang=zh)
  is an optional configured provider.
- [Yuxi](https://github.com/xerrors/Yuxi) informed the document knowledge-base
  and knowledge-graph management workflow. The reference review used tag
  `v0.7.1.beta1` (`c765d904`), released under the MIT License. This project
  adapts the workflow to its existing local worker, SQLite storage, and Control
  Center design; it does not copy or redistribute Yuxi source code or import
  Yuxi's Neo4j/PostgreSQL/Milvus runtime stack.
- [VCPToolBox](https://github.com/lioensky/VCPToolBox) informed the live browser
  perception and human-Agent co-browsing direction. Browser Co-pilot is a
  project-native implementation built on this repository's existing approval,
  SQLite, Agent Tool, and Control Center contracts rather than copied VCP
  extension source.
