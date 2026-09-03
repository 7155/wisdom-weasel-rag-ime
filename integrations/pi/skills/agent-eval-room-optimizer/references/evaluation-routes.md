# Evaluation Routes

Read this reference after Agent Lab has supplied an `evaluationKind`. Select
one primary route. A secondary route is allowed only when retained evidence
shows a real cross-owner dependency.

<!-- AGENT_EVAL_ROOM_ROUTE_CONTRACT_V1 -->
```json
{
  "schemaVersion": "paw.agent-eval-room-route.v1",
  "routes": [
    {
      "evaluationKind": "rag_retrieval",
      "primaryOwner": "knowledge_retrieval_pipeline",
      "diagnosticMethod": "rag-retrieval-optimization",
      "candidateBoundary": "Change one parsing, chunking, retrieval, reranking, packing, or bounded Agentic-retrieval family in a new Validation sandbox.",
      "tracePolicy": "optional"
    },
    {
      "evaluationKind": "answer_citation",
      "primaryOwner": "answer_synthesis_or_evidence_evaluator",
      "diagnosticMethod": "systematic-debugging",
      "candidateBoundary": "Localize retrieval, synthesis, citation binding, abstention, or evaluator ownership before changing one layer; never expose answer Gold to the Agent.",
      "tracePolicy": "optional"
    },
    {
      "evaluationKind": "tool_runtime",
      "primaryOwner": "tool_or_runtime_contract",
      "diagnosticMethod": "systematic-debugging",
      "candidateBoundary": "Repair the first failing Tool or Runtime boundary with a deterministic canary before a new Validation run.",
      "tracePolicy": "optional"
    },
    {
      "evaluationKind": "workflow",
      "primaryOwner": "prompt_or_workflow_state_model",
      "diagnosticMethod": "systematic-debugging_then_implementation-planning",
      "candidateBoundary": "Change one dependency, state, retry, resume, delegation, or verification contract without changing the task or scorer.",
      "tracePolicy": "optional"
    },
    {
      "evaluationKind": "memory",
      "primaryOwner": "memory_recall_or_governance_pipeline",
      "diagnosticMethod": "memory_eval_then_memory-curation_when_authorized",
      "candidateBoundary": "Change one recall, provenance, conflict, freshness, consolidation, or governance seam in a new representative Validation sandbox.",
      "tracePolicy": "optional"
    },
    {
      "evaluationKind": "model_cost",
      "primaryOwner": "model_route_and_usage_metering",
      "diagnosticMethod": "agent-eval-room-optimizer",
      "candidateBoundary": "Keep Prompt, Skill, Tool, Workflow, case-set, verifier and runtime fixed; change one model route, and compare cost only after equal quality and complete usage receipts.",
      "tracePolicy": "optional"
    }
  ]
}
```

## Routing Notes

- `rag_retrieval`: use retrieval labels only inside the Host scorer. Preserve
  index generation and query-time fingerprints separately.
- `answer_citation`: answer correctness, evidence availability, citation
  resolution, fact support, and abstention are different denominators. Do not
  tune retrieval until evidence places the first miss there.
- `tool_runtime`: distinguish Provider failure, Tool input, transport,
  execution, timeout, cancellation, terminal settlement, and report projection.
- `workflow`: test the declared state machine and attempt contract; do not turn
  a prompt reminder into a Runtime guarantee.
- `memory`: keep personal Memory separate from Knowledge RAG and do not expose
  private recalled content in Room-wide evidence.
