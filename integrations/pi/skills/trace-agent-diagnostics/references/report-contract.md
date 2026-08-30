# Trace Inspection And Report Contract

Read this reference whenever the diagnosis covers multiple targets or must be
persisted as a web report.

## Extraction

Call `trace_diagnostics.inspect` once with 1 to 12 targets:

```json
{
  "op": "inspect",
  "targets": [
    {"kind": "session", "id": "agent:...", "title": "...", "traceIds": []},
    {"kind": "room", "id": "room:...", "title": "...", "traceIds": []}
  ]
}
```

Preserve target order and `targetKey`. Treat `sourceAvailable=false` and every
`truncated` flag as a proof boundary. Public Session projections may omit
private reasoning and raw Tool data; never fill those gaps from imagination.
Each conclusion must cite returned `evidenceId` values.

## Result JSON

The final envelope contains exactly:

```json
{
  "schemaVersion": "rag-ime.trace-diagnostic-result.v1",
  "summary": "concise overall diagnosis",
  "hardGates": [
    {
      "gateId": "task_completion",
      "status": "passed | failed | unknown",
      "reason": "...",
      "evidenceIds": []
    }
  ],
  "judgeScores": [
    {
      "dimensionId": "context",
      "score": 0,
      "authority": "ai_judge_estimate",
      "explanation": "...",
      "evidenceIds": []
    }
  ],
  "findings": [
    {
      "findingId": "finding:stable-id",
      "dimensionId": "tool_runtime",
      "severity": "critical | high | medium | low",
      "observation": "directly observed fact",
      "hypothesis": "remaining explanation, or empty",
      "conclusion": "supported owner/cause, or empty",
      "confidence": "high | medium | low | unknown",
      "evidenceIds": [],
      "candidateRepair": "unapplied proposal",
      "verification": "checks required after authorization"
    }
  ]
}
```

Valid dimensions are `task_completion`, `evidence_diagnosis`, `tool_runtime`,
`context`, `room_collaboration`, `memory_rag`, `efficiency`, and
`repair_quality`. Judge scores are integers 0-3 or null. Runtime owns the
deterministic scorecard already present in the frozen inspection; do not copy
or overwrite it in `judgeScores`.

For a multi-target report, name the relevant `targetKey` in each finding's
text and cite target-bound evidence. A shared Trace is not permission to erase
which selected object owned the event.
