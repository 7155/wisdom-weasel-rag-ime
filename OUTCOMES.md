# Project Outcomes

Updated: 2026-09-07

Statuses describe focus; Runtime owns activity, worktree
state and Tool progress.

## Evidence Boundary

Separate source, installation, foreground, and distribution evidence. Verify
Git and Runtime live; `release/product-status.json` and its audit record release gates.

## Current Focus

| ID | User result | Status | Current evidence boundary | Next acceptance frontier |
| --- | --- | --- | --- | --- |
| O1 | Session can work reliably for a long time | active | Earlier installed canaries passed activity, Steer, Stop, Tool closure, and refresh; the 2026-09-04 isolated source PAWOS additionally proved exact client/turn identity, observer-safe replay, restart/idempotent recovery, and two exactly-once foreground turns across refresh | Install this candidate, then run a long soak plus compaction/recovery and permission acceptance |
| O2 | Room completes a real collaboration by composing Pi Sessions | active | The 2026-09-03 installed build proved persisted conversation-first history, full-trust participants, simultaneous live updates, one terminal Root, refresh recovery, and selected-moderator Runtime prewarming; fresh probes measured Provider first text in 2.57–2.58 s while total Room first text varied 6.54–8.58 s | Run a multi-day reconnect/cancellation soak; if visible first text must stay below 7 s, separately bound pre-Provider routing and query-aware memory bootstrap |
| O3 | A parent Session can use configurable private Tool Agents | active | Current source supports bounded child events/results, read/write choice, model/thinking override, and same-tree peer calls | Prove a useful live parent/child run, then raise capacity through bounded event/UI/resource budgets rather than more Kernel state |
| O4 | PAW can develop itself through a bounded context and Skill harness | active | The installed managed Pi enforces revisioned four-scenario Skill allowlists; Settings/catalog checks proved mandatory Room/Trace/Lab isolation, and `resume-builder` is absent | Finish foreground 掌柜问数 acceptance and Package uninstall/restore |
| O5 | Control Center truthfully renders Session and Room state | active | Development build 1429 and compact-trace Pi installed; installed HTTP Room recovery, messages/models and OAuth probe passed ([causal record](control-center-web/docs/pawos/PAWOS_RELIABILITY_CONTINUATION_20260905.md)) | Verify resident trace and native multi-window recovery; finish [stellar/Memory](control-center-web/docs/pawos/STELLAR_MEMORY_TOPIC_PAGES_20260905.md), Knowledge and Lab flows |
| O6 | Memory, Knowledge, and Agent evaluation provide governed, explainable context | active | Four scenario projections: EnterpriseOps 3/3 and 31/31, estimate $1.711214→$0.07291692 (-95.7389%); Enterprise RAG r6 Sol 7/9 Reject → Luna 8/9 Reject → Luna+Prompt-v4 9/9 Keep, $2.170603→$0.1029376 (-95.2576%); CloudOps CA 1.0 and JRA 0.8333→0.9167, $4.568166→$0.27613024 (-93.9553%); Memory's separate Pi model-only synthetic pair: 5/5 curation, 4/4 durable recall, 1/1 abstention plus rollback/replay, Runtime-reconciled estimate $0.163425→$0.0071846 (-95.6037%), 4 requests, 0 failures. Separate standard-v1 Pi and concise-v1 CLI records remain. Costs are Runtime-reconciled estimates, not bills. RAG r6 remains candidate-aware/post-Validation, not candidate-blind/Held-out/unbiased; Standard correction is not model improvement; latency is diagnostic. | [Generic Lab](control-center-web/docs/pawos/LAB_GENERIC_WORKBENCH_ACCEPTANCE_20260907.md)/[Knowledge App](control-center-web/docs/pawos/LAB_KNOWLEDGE_FRONTEND_FLOW_20260907.md) verified locally; Golden inconclusive. Next: installed/cloud verification. [UR-284–UR-291](control-center-web/docs/pawos/requirements/PAWOS_REQUIREMENTS_284_291.md) retain the optimization contract: verify task success/cost using model, tool, prompt, Skill and workflow/Harness candidates; Validate installed Prompt/Model controls, Memory Pi adapter and demo export ([receipts](control-center-web/docs/pawos/LAB_GOLDEN_WORKFLOW_20260905.md)); finish scene adapters and real counterfactual/Tool/Skill trials; require candidate-blind or untouched Held-out RAG evidence for unbiased Promotion; [8 Lab records](eval/micro-selfboot/OS_RESULTS.md); [Room merge](eval/micro-selfboot/OPTIMIZATION_RESULTS.md) retains 3/3: tokens -35.5%, estimated cost -24.7% |
| O7 | The macOS input experience is correct in real foreground apps | active | [Generation review](squirrel-patches/GENERATION_EXPERIENCE.md); [screen continuation](squirrel-patches/SCENARIO_INTEGRATION.md): tasks/recovery checked; Squirrel and Electron built, uninstalled; native capture/full-web checks blocked | Restore native observation, resolve web regression; install matching Squirrel/Electron/Gateway; verify selection, vision follow-up, saves and desktop Tools, then remaining input/voice cases |
| O8 | A public macOS release is reproducible and distributable | blocked | Scoped source preview `v0.1.0-alpha.1`; engineering builds exist | Current distribution manifest, candidate-quality sign-off, Developer ID signing, notarization, stapling, clean-machine installation, and accepted foreground evidence |
| O9 | React OS provides the PAWOS frontend while Pi/Gateway retain Runtime ownership | active | A selectable PAW OS shell provides Wayfinder, grouped App identities, windows, Dock, Launchpad, Mission Control, and three reference-aligned themes while the legacy shell remains available; Browser maps its visible tab and address bar to the governed PAW `deviceId + tabId` command path | Finish App flows, native recovery and whole-OS acceptance; [galaxy, dark mode and Browser libraries](control-center-web/docs/pawos/STELLAR_BROWSER_CONTINUATION_20260905.md) have source checks |

## O1 — Long-Running Session

Acceptance requires one current Runtime/build:

- Luna shows useful text or a public thinking summary without an indefinitely
  empty “thinking” card. Five seconds is an experience target, not a forced
  timeout.
- Steer uses Pi's native Session path and the user message appears before its
  queued/processing event.
- Stop immediately projects `stopping`, covers the pre-turn admission window,
  and reaches a real terminal or escalated cancellation state.
- Every Tool success, rejection, failure, and cancellation closes its Tool card.
- Refresh reconstructs durable history plus only the real live tail; it cannot
  create a zero-message ghost turn.
- Public Tool results stay within one round-level budget rather than multiplying
  a per-Tool limit.

The 2026-08-16 installed receipt covered activity, Steer, Stop, Tool closure,
refresh, and bounded public Tool payloads. It is not a multi-day soak or public
release claim.

[Fault matrix](eval/execution-reliability/README.md): 45/45 source checks.

## O2 — Lightweight Room

The accepted design is one Facilitator Session plus zero or more visible Partner
Sessions. Partners may use private Tool Agents. Pi owns each Session; Room owns
collaboration identity, explicit dispatch, ordered public events, cancellation
fan-out, and one terminal Root.

The 2026-09-03 installed Room receipt covered immediate optimistic text,
multi-window results, one Root, reload recovery, prewarming, and layered
`full_trust`. Provider first text was 2.57–2.58 seconds while end-to-end Room
first text was 6.54–8.58 seconds, leaving pre-Provider routing and memory work
as the measured frontier before a reconnect/cancellation soak.

## O3 — Tool Agent Capacity

Tool Agents are the parent Session's private hands, not miniature Room members.
The parent selects their task, context refs, Skills, model/model card, thinking,
access, tools, workspace, and peer-call permission. A child result has
`evidence_only` authority until its parent verifies and integrates it.

Scale concurrency through pagination, bounded results, cancellation, resource
budgets and compact UI. Current parallel/depth limits constrain implementation.

## O4 — Self-Hosting Harness

The root bootstrap and eight core Skills are the first self-hosting layer. The
background organizer keeps accepted documents linked and compact, while active
Agents own the meaning they produce. A live self-hosting canary should verify
that a new Session reads only the current Outcome and selected refs, chooses no
unnecessary Skill, performs a real change, and returns a bounded `AgentResult`.

The Pi Package ability market accepts npm, Git, local, and catalog sources,
previews before mutation, and records versions for update and rollback.
`plugin-creator` reuses first and stops at product confirmation.

The 2026-09-03 development installation exposes revisioned ordinary, Room,
Trace and Agent Lab Skill routes in Settings and enforces the selected
allowlists at `session.open`. Mandatory private Skills remain exact-scenario
only; an Agent Lab Room receives both Lab and Room capabilities. The removed
`resume-builder` no longer appears in the installed catalog.

New projects initialize only when the user invokes Pi's `/init` prompt
template. It inspects the bound workspace and creates or narrowly supplements
the root `AGENTS.md`; Session creation never writes project files.

The [2026-09-06 prompt-settings candidate](eval/micro-selfboot/PROMPT_SETTINGS_REVIEW.md)
adds editable system/compaction additions and docs-aware summaries, with Session
binding snapshots. Source checks and isolated Settings acceptance passed; the
new Host is staged inactive. Paired activation awaits a safe Gateway restart;
the running installation still uses its existing prompts.

## O5–O8 — Product Surfaces And Release

Session/Room success does not prove whole-product readiness. UI requires Runtime
truth, Memory requires provenance and evaluation, native adapters require foreground
evidence, and distribution requires current release gates.

The [2026-09-06 memory continuity result](eval/memory-topic-selfboot/RESULT.md)
adds Book reuse, automatic topic aggregation, conversation switches and summaries. Development
required Session recovery; unattended self-hosting remains unproven.

[Source integration](control-center-web/docs/pawos/INTEGRATION_CLOSEOUT_20260906.md); installation acceptance remains separate.

## Condensed History

Retired Room/Kernel workflows and mandatory review pipelines remain historical.
Migrations stay append-only; delete replaced paths only after proving no consumers.
