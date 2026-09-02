---
name: trace-agent-diagnostics
description: Diagnose one or several selected PAW Sessions, Rooms, or runs from canonical public Trace and Eval evidence; use when the Trace Agent App must score execution quality, explain failures or waste, persist an evidence-linked report, and propose a repair that still requires explicit user authorization. Do not use for generic log summarization or direct mutation.
---

# Diagnose Agent Traces

Turn a bounded selection of PAW execution objects into a persisted,
evidence-linked diagnostic report. The diagnostic Session is read-only. It
produces a candidate repair but never treats the candidate, a generated handoff,
or an Agent claim as an applied fix.

Use `trace_diagnostics.inspect` before diagnosing. It is the model-visible
public projection owned by Runtime; `session_search` summaries and prompt text
are not substitutes for the selected transcript/Trace evidence.

## Select And Bound The Case

1. Preserve the submitted target order and object boundary. Accept 1 to 12
   `session`, `room`, or `run` targets and call
   `trace_diagnostics.inspect({op: "inspect", targets: [...]})` once. Do not
   silently replace a missing target with its latest neighbor.
2. Treat the returned inspection, fingerprint, Trace bindings, coverage,
   evidence IDs, requirement candidates, environment snapshot, hard gates, and
   deterministic metrics as frozen facts for this report. Never cite an
   evidence ID or requirement ID outside that inspection.
3. Resolve the selected object to stable `sessionId`, `roomId`, `runId`,
   `traceId`, WorkItem IDs and an explicit time or turn range. A Room case
   includes its Facilitator, planet Sessions, subagents, dispatches, public
   events and Tool runs for that range when those public projections exist.
4. State the observed symptom and expected behavior. Preserve the user's
   visible failure separately from Runtime status, WorkItem state and Eval
   quality; one recoverable Tool error does not make an entire planet failed.
5. Set a bounded investigation budget for queries, replay attempts and model
   calls. Stop when the leading cause is supported, the next discriminating
   experiment requires new authority, or the budget cannot distinguish the
   remaining hypotheses.

## Build The Evidence Slice

Read canonical data first: terminal run errors, span status and timing, parent
and retry links, Tool arguments and receipts, cancellation, WorkItem ownership
and revisions, context assembly/compaction, retrieval evidence, token usage,
artifacts and EvalRuns. Use transcript prose only to understand intent; it does
not prove that a Tool ran, a document bound, a file changed or a result passed.

Choose the smallest relevant diagnostic lane:

- **Tool, Browser, Runtime:** find the first failing span and distinguish
  invalid input, unavailable capability, queueing, timeout, stale guest/runtime,
  cancellation, provider failure and downstream consequence. Compare a nearby
  successful run when available.
- **WorkDocument and artifact:** trace authority revision, transition receipt,
  active/archive state, canonical path, file write and registration receipt.
  Separate generated content from an accepted authority-bound document.
- **Context:** inspect what the model actually received, compaction boundaries,
  duplicate or stale injections, missing requirements, irrelevant retrieval and
  token distribution. Do not infer context from the final response.
- **Room collaboration:** reconstruct dispatch, acceptance, ownership,
  reassignment, review and return loops. Flag duplicated scopes, idle planets,
  serial work that could be independent, excessive fan-out, incompatible owner
  boundaries, repeated review with unchanged evidence and orphaned WorkItems.
- **Memory:** evaluate recall relevance, coverage, conflict handling, freshness,
  provenance and harmful injection using a representative Memory EvalRun.
- **Knowledge/RAG:** inspect parse, chunk, candidate, rerank, packing, citation
  and abstention traces. Route an authorized retrieval change through
  `rag-retrieval-optimization`; never tune from one anecdote.
- **Efficiency:** attribute latency and token use to useful output, retries,
  repeated Tool calls, duplicated context, unnecessary delegation and rework.
  Report waste only with comparable traces or a clear counterfactual workflow.

Before opening a lane, prove its applicability from the selected object and the
frozen inspection. The object type supplies only a starting hypothesis:

- a Memory maintenance run starts with source read, consolidation output,
  conflict/deduplication, validation, persistence, and the Runtime failure
  chain; it does not automatically activate Knowledge/RAG retrieval;
- a Room target activates collaboration only when the inspection contains
  Room, WorkItem, dispatch, Partner, or child-Agent bindings;
- a standalone or background run without those bindings has collaboration
  `not_applicable`; their absence is not a finding;
- Context and efficiency activate only when the inspection exposes the
  corresponding source, budget, token, byte, timing, retry, or comparison
  evidence.

After `inspect`, state the active primary lane, optional secondary lanes, and
inactive lanes. A lane with no matching capability is `not_applicable`, not
`unknown`. Do not emit a `judgeScore` or `finding` for an inactive lane. Keep
one primary cause and at most three direct consequences or indispensable
evidence gaps. Never manufacture one finding per score row.

Keep observations, hypotheses and conclusions in distinct report fields. Run one
discriminating experiment at a time. A plausible stack frame or repeated error
message is not yet a root cause if an upstream owner first produced the bad
state.

Assess only requirement IDs already frozen by Runtime. A user message row is a
source candidate, not proof that it was satisfied. Do not split, merge, or
invent requirements inside the result envelope. Likewise, chronological
adjacency is not causality: emit a `causalLink` only when the cited public
evidence supports the direction, and keep its authority as
`ai_judge_estimate`.

## Attribute Every Failure Across Five Layers

Every newly emitted result must include `presentation.failureAttribution`. This
is a plain-language, evidence-linked decision about all five possible owners,
always in this exact order:

1. `tool` — Tool invocation, receipt, schema, capability, or Runtime effect.
2. `skill` — The diagnostic or task Skill's instructions and required checks.
3. `template` — The task template, prompt, or compiled prompt inputs.
4. `workflow` — Session/Room sequencing, routing, retries, ownership, or policy.
5. `model` — Model capability or execution after the other layers are adequately
   observed.

The object has exactly `primaryLayer`, `summary`, and `layers`. `primaryLayer`
is one of `tool|skill|template|workflow|model|unknown`; `layers` has exactly
five entries in the order above. Each entry has exactly `layer`, `verdict`,
`explanation`, and `evidenceIds`. A verdict is one of
`primary|contributing|healthy|unknown|not_applicable`. Emit at most one
`primary`; when no primary is defensible, use `primaryLayer: "unknown"` and
do not emit a primary verdict. Every `primary`, `contributing`, or `healthy`
claim must cite frozen inspection Evidence IDs. Use `unknown` when the
inspection cannot distinguish a layer and `not_applicable` only when that
layer is outside the case.

Treat Tool receipts as decisive for the Tool layer: if a Tool ran and its
receipt shows the requested effect succeeded, mark `tool` `healthy` even when
the final task outcome is wrong. Do not blame the model until the model's
inputs/outputs and the Skill, template/prompt, workflow, and Tool evidence are
adequate to exclude those owners. A model error message or a plausible final
answer is not model-capability evidence by itself. Keep the attribution
summary understandable without Runtime terminology, then cite the exact
Evidence IDs in the layer entries.

## Score Without Inventing Certainty

The deterministic web report always renders these eight rows: task completion,
evidence and diagnosis, Tool/Runtime reliability, Context, Room collaboration,
Memory/RAG, efficiency, and repair quality. The diagnostic Agent does not need
to emit eight `judgeScores`; it emits semantic scores only for active lanes
supported by evidence. Inactive rows remain `not_applicable` in the report
projection instead of becoming speculative prose.

- Runtime calculations are `deterministic`; frozen labelled EvalRuns are
  `ground_truth`; semantic 0–3 assessments are `ai_judge_estimate`. Never blend
  those authorities into one unexplained number.
- Use `not_applicable` only when the capability is outside the case,
  `unavailable` when the expected authority could not be read, and `unknown`
  when evidence is incomplete or contradictory. None means zero.
- A completion hard gate cannot be averaged away by low Token cost. Do not call
  a task complete from assistant prose without artifact, test, install, Runtime,
  or explicit acceptance evidence appropriate to the requirement.
- Compare cost, time, repair effect, or before/after quality only when the
  workload, success criteria, fixture/data revision, model/config/tool profile,
  and measurement authority are comparable. Otherwise show separate absolute
  values and the reason comparison is blocked.

For anchors and metric rules, read
[references/scoring-rubric.md](references/scoring-rubric.md). For multi-target
extraction, evidence boundaries, and the exact result envelope, read
[references/report-contract.md](references/report-contract.md).

## Recommend, Repair, And Verify

Produce the smallest candidate change that addresses the confirmed owner: code, config,
prompt, routing, WorkItem assignment, retrieval profile or operational action.
Label unsupported explanations as hypotheses.

Trace verification requires a governed sandbox replay. For a registered
vertical suite, use the installed `vertical-agent-sandbox` Connector and retain
its SandboxRun, Trace and EvalRun identities. For a workspace repair, run the
representative test through the Host-owned `workspace_shell` command harness
with network blocked; an ordinary or model-claimed successful command is not
sandbox evidence. If no representative replay exists, keep repair quality
`unknown` or `blocked` and do not mark the candidate verified.

The diagnostic Session is always read-only: it has no write roots and no
mutation tools. “Repair” is a separate explicit product confirmation that
creates a Trace repair Session with this exact policy:

- `mode: "coordinator"`
- `toolProfileVersion: "control-center-auto-approve-v1"`
- `executionMode: "full_trust"`
- `dangerousModeConfirmation: "ENABLE_FULL_TRUST"`
- `workspaceRoots: ["/"]`
- `toolAllowlistMode: "profile"`
- `projectContextEnabled: true`, `piSkillsEnabled: true`, and
  `codexSkillsEnabled: true`

The completed-report UI keeps one explicit confirmation that explains this
full-disk/all-tool automatic authority. The profile automatically approves
every Tool effect; it does not require source-workspace equality or PAW
workspace-scope/approval hashes. Direct OS/TCC/Unix permissions can still be
the final boundary. The repair Agent must not ask the user to type a
directory or `ENABLE_FULL_TRUST` again, and must not ask for per-Tool
approval. A URL handoff never supplies authority.

Creating a repair handoff does not mean that a repair was applied. Report
candidate/unapplied when authorization is absent or denied. Only a new
Trace/Eval receipt after the authorized Agent action may mark the repair
verified; never infer install or foreground acceptance.

Persist new authorization receipts with
`writeAuthority: "auto_approved_full_trust"`; older
`"per_action_required"` and `"model_arbitrated_full_trust"` values remain
readable.

The report must stop at a candidate repair. The UI asks the user whether to
continue; only the explicit confirmation may create the Trace repair Session.
Read [references/repair-verification.md](references/repair-verification.md)
when the user authorizes that second phase.

## Report Contract

### Mandatory Exact-Envelope Checklist

Immediately before emitting the final envelope, validate the JSON itself against
this checklist. This check is mandatory even when the diagnosis prose is
correct:

1. Allowed top-level keys (complete allowlist): `["schemaVersion","summary","presentation","hardGates","judgeScores","requirementAssessments","causalLinks","findings"]`
2. Required top-level keys: `["schemaVersion","summary","presentation","hardGates","judgeScores","findings"]`
   This required list applies to every newly emitted result.
   `requirementAssessments` and `causalLinks` are optional; no other top-level
   key is permitted. The Runtime accepts an older persisted v1 result without
   `presentation`, but a new diagnostic result must emit it. Do not add
   convenient aliases such as `target`,
   `observations`, `hypotheses`, `conclusions`, or `repairCandidate`.
3. Treat the top-level result and every nested result object as
   `additionalProperties=false`: use only the fields shown in
   `references/report-contract.md`. Never rename a field, add a prose-only
   companion field, or move a finding field to the top level.
4. Every finding or causal-link `confidence` MUST be a JSON string: `"high"`, `"medium"`, `"low"`, or `"unknown"`.
   Numeric confidence values such as `1` or `0.95` are invalid; never emit them
   and never rely on Runtime to coerce them.
5. When frozen evidence is absent, use `"evidenceIds": []` and never invent an
   ID. For an emitted evidence-gap finding use `"confidence": "unknown"`; for
   an unverified hard gate use `"status": "unknown"`; for an unjudgeable
   active score use `"score": null`; and for a frozen requirement without
   proof use `"status": "unverified"`. Do not emit a causal link unless both
   endpoint evidence IDs exist in the inspection.
6. Empty supported collections remain arrays, not substitute objects or prose:
   emit `"hardGates": []`, `"judgeScores": []`, and `"findings": []` when
   there are no valid entries. Optional `requirementAssessments` and
   `causalLinks` may be omitted or emitted as `[]`.
7. `presentation` is the bounded plain-language scan layer. Emit exactly these
   fields: `headline`, `impact`, `primaryFindingId`, `knownFacts`,
   `evidenceGaps`, `causalNodes`, `expectedStageCount`,
   `recordedStageReceiptEvidenceIds`, and `failureAttribution`. Put one
   independently understandable outcome in `headline`, and explain the
   user-visible consequence in `impact` before naming internal components.
   `primaryFindingId` is empty or matches an emitted finding. Every known fact
   and causal node cites one or more frozen Evidence IDs. A causal node is
   `confirmed` only when its cited Evidence proves that step; otherwise use
   `unverified`. Each evidence gap states the missing fact, why it matters, and
   how to obtain it. Count only authoritative expected stages and recorded
   stage-receipt Evidence; if the inspection does not freeze an expected-stage
   contract, emit `expectedStageCount: 0` and do not present that zero as proof
   that no stage was expected.
8. `failureAttribution` is required for every new result and optional only when
   reading an older persisted v1 result. Emit exactly:
   `{ "primaryLayer", "summary", "layers" }`, with `layers` containing exactly
   five entries in order `tool`, `skill`, `template`, `workflow`, `model`.
   Each entry has exactly `layer`, `verdict`, `explanation`, and `evidenceIds`;
   verdicts are `primary`, `contributing`, `healthy`, `unknown`, or
   `not_applicable`. Emit at most one `primary`, and make `primaryLayer`
   match it; if no primary is defensible, use `primaryLayer: "unknown"`.
   `primary`, `contributing`, and `healthy` require frozen Evidence IDs.
   Mark Tool `healthy` when a receipt proves the Tool effect worked, even if
   the final outcome is wrong. Do not blame the model until input, Skill,
   template/prompt, workflow, and Tool evidence is adequate; otherwise use
   `unknown`. Attribute the summary in plain user language.

End the diagnostic Session with exactly one machine-readable result envelope:

```markdown
--- TRACE_DIAGNOSTIC_RESULT_V1 ---
{ "schemaVersion": "rag-ime.trace-diagnostic-result.v1", ... }
--- END_TRACE_DIAGNOSTIC_RESULT_V1 ---
```

The JSON must match the field contract in `references/report-contract.md`.
Runtime re-parses it, rejects unknown evidence IDs, and persists an immutable
report revision. The result may assess frozen requirements and add explicit
evidence-to-evidence causal links; it must not rewrite the frozen source text,
environment, timeline, or evidence catalog. Text outside the envelope is
explanatory only and is not the
web report authority. The in-product engineering audit page and downloadable
HTML are deterministic projections of that persisted revision; the Skill never
emits executable HTML, CSS, or JavaScript. Prefer a short set of high-signal
findings over a dump of events. Do not expose private transcript text, raw Tool
arguments, Provider context, credentials, or machine paths.

Keep explanatory text before the envelope to at most six lines: report identity,
primary cause, impact, the most important unknown, and the next authorized
action. Write `summary`, the visible cause, impact, candidate repair, and next
action in plain user language: describe what did not finish or what the user
cannot do before naming an internal Host, settlement call, JSONL boundary,
provider, span, schema, or policy revision. Put those implementation names in
finding evidence/details so the compact receipt remains understandable without
Runtime knowledge. Do not duplicate the full report in conversation prose; the Session UI
projects the completed envelope as a compact receipt and the persisted web page
owns the detailed presentation.

Read the HTML projection boundary in
[references/report-contract.md](references/report-contract.md) before changing
the result envelope for presentation needs. A visual requirement must not add
unverified prose or private evidence to the report contract.
