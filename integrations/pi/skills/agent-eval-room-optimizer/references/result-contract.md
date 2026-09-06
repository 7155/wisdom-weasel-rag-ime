# Result Contract

Use this semantic contract for the Facilitator's integrated result. The owning
product may project it into its versioned report schema; do not invent aliases
that lose attribution, verifier authority, or proof boundaries.

<!-- AGENT_EVAL_ROOM_RESULT_CONTRACT_V1 -->
```json
{
  "schemaVersion": "paw.agent-eval-room-result.v1",
  "evaluationKind": "workflow",
  "roomGoalRef": "room-goal:durable-receipt",
  "before": {
    "runRef": "eval-run:before",
    "caseRefs": ["case:public-alias"],
    "evidenceRefs": ["evidence:before-receipt"],
    "metrics": {}
  },
  "finding": {
    "targetLayer": "workflow",
    "summary": "One evidence-supported primary cause.",
    "evidenceRefs": ["evidence:first-failing-boundary"],
    "proofBoundary": "Known historical evidence only."
  },
  "candidateChange": {
    "summary": "One bounded candidate change.",
    "targetObject": "prompt",
    "candidateType": "single_factor",
    "effectStatus": "improved",
    "targetMetric": "verifier_pass_rate",
    "expectedDirection": "max",
    "validationSplitRef": "validation:same-frozen-case-set",
    "sandboxRef": "sandbox:fresh-run",
    "authorizationStatus": "bound_user_dispatch"
  },
  "after": {
    "runRef": "eval-run:after",
    "evidenceRefs": ["evidence:host-verifier-receipt"],
    "metrics": {},
    "passFailAuthority": "host_verifier"
  },
  "delta": {
    "comparable": false,
    "metrics": {},
    "reason": "Set true only after every frozen comparison field matches."
  },
  "decision": {
    "value": "Reject",
    "reasonCodes": ["host_gate_not_passed"]
  },
  "attribution": {
    "detectedBy": "actor:evidence-owner",
    "proposedBy": "actor:candidate-owner",
    "authorizedBy": "actor:approval-receipt-or-unknown",
    "implementedBy": "actor:implementation-receipt-or-unknown",
    "verifiedBy": "host_verifier"
  },
  "facilitatorTerminal": {
    "kind": "result_or_blocked",
    "receiptRef": "room-post:single-terminal"
  },
  "star": {
    "situation": "State the frozen evaluation context and observed gap.",
    "task": "State the owned optimization target and acceptance contract.",
    "action": "State only authorized and evidenced actions with actor attribution.",
    "result": "State comparable before and after metrics plus the decision.",
    "proofBoundary": "State sample, split, runtime, installation, and generalization limits.",
    "resumeRef": "room-result:durable-evidence-index"
  },
  "boundaries": [
    "No raw Gold or private evidence is present.",
    "A Validation result is not promotion or production acceptance."
  ]
}
```

## Decision Rules

- `Keep`: the candidate clears its target failure, all declared Host gates pass,
  and no protected regression appears in comparable Validation evidence.
- `Keep` is an optimization claim only when `effectStatus=improved`. A quality
  tie without a measured efficiency/cost gain is `neutral`, not an improvement.
- `Reject`: the target failure remains, evidence is incomparable, or a hard gate
  fails. Preserve the candidate and failure receipts.
- `Rollback`: a previously applied candidate causes a protected regression and
  an authorized rollback receipt exists. A recommendation alone is not a
  rollback.

When no after run is authorized, leave the candidate unapplied, keep after and
delta unverified in the product projection, and write the STAR result as a
diagnosis/proposal rather than a completed optimization.

For an App-supplied `agentLabDispatch`, preserve its objective, scope, budget,
stop conditions, selected repair operator and counterfactual probe identity in
the candidate receipt. Record all tried candidate numbers, cumulative actual
usage and the terminal reason. `no_improvement` is a completed search outcome;
it does not promote a rejected candidate. `agent_observed` budget compliance
must not be described as a Host-enforced cumulative cost ceiling.

Keep `regressed`, `not_run`, and `unverified` candidates visible as rejected or
pending evidence, but do not count them in a scene's successful optimization
total. If more than one layer changed in one candidate, set
`candidateType=compound_repair` and do not attribute its delta to an individual
Prompt, Tool, Skill, Workflow, Model, or RAG layer.
