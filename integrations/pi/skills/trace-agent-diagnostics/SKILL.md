---
name: trace-agent-diagnostics
description: Diagnose a selected PAW Session, Room, subagent, Tool run, Memory recall, or Knowledge/RAG run from canonical Trace and Eval evidence; use when the Trace Agent App must explain failures, context defects, collaboration waste, repeated rework, or token inefficiency and propose or verify a repair. Do not use for a known one-line UI change or generic log summarization.
---

# Diagnose Agent Traces

Turn one user-selected Session, Room, subagent run, or vertical application run
into an evidence-linked diagnosis and, when authorized, a measured repair. The
Trace Agent consumes PAW's existing Runtime, TraceStore, EvalRun, WorkItem and
artifact authorities; it does not invent a second event history.

## Select And Bound The Case

1. Resolve the selected object to stable `sessionId`, `roomId`, `runId`,
   `traceId`, WorkItem IDs and an explicit time or turn range. A Room case
   includes its Facilitator, planet Sessions, subagents, dispatches, public
   events and Tool runs for that range.
2. State the observed symptom and expected behavior. Preserve the user's
   visible failure separately from Runtime status, WorkItem state and Eval
   quality; one recoverable Tool error does not make an entire planet failed.
3. Set a bounded investigation budget for queries, replay attempts and model
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

Keep observations, hypotheses and conclusions distinct. Run one
discriminating experiment at a time. A plausible stack frame or repeated error
message is not yet a root cause if an upstream owner first produced the bad
state.

## Recommend, Repair, And Verify

Produce the smallest change that addresses the confirmed owner: code, config,
prompt, routing, WorkItem assignment, retrieval profile or operational action.
Label unsupported explanations as hypotheses.

The diagnostic Session is always read-only: it has no write roots and no
mutation tools. “Repair” is a separate explicit user action that creates an
ordinary Agent Session under its normal per-action approval and the exact
authorized workspace roots. Creating a repair handoff does not mean that a
repair was applied. Report candidate/unapplied when authorization is absent or
denied. Only a new Trace/Eval receipt after the authorized Agent action may mark
the repair verified; never infer install or foreground acceptance.

The Trace Agent may modify a target only when the user has authorized that
mutation. Apply the change as an ordinary scoped Agent task with a visible diff
and receipts. Replay representative cases in the managed sandbox, persist the
new Trace and EvalRun, and compare the same metrics and evidence contract before
and after. A sandbox win is a candidate result, not installed or foreground
acceptance. Preserve the previous configuration or revision as the rollback
target and observe the repaired path after application.

## Report Contract

Create a desktop report that contains:

```text
selected object and range | user-visible symptom | impact
timeline/topology summary | finding IDs with severity
evidence links to run/span/WorkItem/file/EvalRun
confirmed cause vs hypotheses | eliminated alternatives
redundant steps, assignment defects and measured token/time waste
recommended change and expected effect
before/after sandbox or Eval evidence | applied/unapplied state
residual risk | rollback target | next action
```

Every finding must jump back to the exact evidence. Prefer a short set of
high-signal findings over a dump of events. Do not silently repair, repeatedly
self-tune against the same cases, expose private transcript text in reports, or
claim that lower token use is better when requirement satisfaction regressed.
