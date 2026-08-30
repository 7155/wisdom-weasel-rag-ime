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

`inspection.requirements.items` contains bounded user-authored source rows.
Assess those stable `requirementId` values; never manufacture a requirement
statement in the result. `inspection.timeline` is chronological unless an
explicit result `causalLink` connects two frozen Evidence rows. The
`inspection.environment` projection contains only Runtime-owned labels,
versions, hashes and limitations; missing fields stay missing.

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
  "requirementAssessments": [
    {
      "requirementId": "a requirementId returned by inspect",
      "status": "satisfied | partial | unsatisfied | unverified",
      "owner": "bounded owner label or empty",
      "authority": "ai_judge_estimate",
      "evidenceIds": [],
      "note": "why this status is or is not supported"
    }
  ],
  "causalLinks": [
    {
      "linkId": "causal:stable-id",
      "fromEvidenceId": "a frozen evidenceId",
      "toEvidenceId": "a frozen evidenceId",
      "relation": "triggered | delegated | responded_to | returned | verified | caused | recovered",
      "authority": "ai_judge_estimate",
      "confidence": "high | medium | low | unknown",
      "explanation": "why this is causal rather than merely chronological"
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

The eight visible report rows are not a requirement to emit eight semantic
scores or findings. Emit a `judgeScore` only for a lane activated by the target
and frozen evidence. A background Memory maintenance run without Room bindings
must not produce a Room finding; lack of an unrelated capability is
`not_applicable`, not an observability defect. Likewise, Memory maintenance and
Knowledge/RAG retrieval share a display row but remain distinct diagnostic
lanes.

For a multi-target report, name the relevant `targetKey` in each finding's
text and cite target-bound evidence. A shared Trace is not permission to erase
which selected object owned the event.

The completed diagnostic result remains immutable. Later repair handoff
authorization and receipt/Eval verification are linked through append-only
report revisions. A repair-handoff authorization creates a separate
`full_trust` repair Session after the user's one-time confirmation; actual
operations remain bound to the one owner workspace and are arbitrated by the
independent Luna Max approval Agent. The handoff itself is not proof that any
mutation ran or passed.

## HTML Projection

The report authority is the immutable persisted JSON revision, not Agent-authored
markup. PAW projects that revision through the fixed engineering-audit template
owned by the Control Center:

```text
persisted report revision
→ normalized audit view
→ in-product report page
→ self-contained downloadable HTML
```

The downloadable file must:

- carry `reportId`, revision, `inspectionSha256`, status, and export time;
- render only the public report projection: targets, frozen requirement rows,
  explicit causal links plus the complete bounded chronological timeline,
  scorecard with metric Evidence, hard gates, findings, the redacted Evidence
  appendix, environment hashes/labels, candidate repair, authorization status,
  and verification/comparison records;
- escape every report-authored string before inserting it into markup;
- contain no external script, font, image, analytics, or network dependency;
- exclude private reasoning, raw Tool arguments, Provider context, credentials,
  machine paths, and unprojected raw inspection payloads;
- label candidate repairs as unapplied until a new Trace/Eval verifies an
  authorized repair.

The causal view never replaces the chronological view. Events without an
explicit `causalLink` remain visible in the complete frozen timeline. Every
score row must preserve the Evidence IDs carried by its deterministic metrics
and AI judge estimate.

Do not put an HTML template in the model result or ask the diagnostic Agent to
write markup. Presentation changes belong to the deterministic template; schema
changes belong here and require Runtime validation updates.
