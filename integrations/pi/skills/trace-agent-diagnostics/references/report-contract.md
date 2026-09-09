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
  "presentation": {
    "headline": "one plain-language conclusion that stands on its own",
    "impact": "what the user could not complete or trust",
    "primaryFindingId": "finding:stable-id or empty",
    "knownFacts": [
      {
        "fact": "one confirmed fact",
        "evidenceIds": ["a frozen evidenceId"]
      }
    ],
    "evidenceGaps": [
      {
        "gap": "what is still unknown",
        "consequence": "which conclusion this prevents",
        "howToObtain": "the next bounded evidence-producing check"
      }
    ],
    "causalNodes": [
      {
        "label": "plain-language step",
        "detail": "bounded technical detail",
        "status": "confirmed | unverified",
        "evidenceIds": ["a frozen evidenceId"]
      }
    ],
    "expectedStageCount": 0,
    "recordedStageReceiptEvidenceIds": [],
    "failureAttribution": {
      "primaryLayer": "unknown",
      "summary": "当前证据不足以确定唯一归因层。",
      "layers": [
        {"layer": "tool", "verdict": "unknown", "explanation": "尚无足够 Tool 回执证据。", "evidenceIds": []},
        {"layer": "skill", "verdict": "unknown", "explanation": "尚无足够 Skill 执行证据。", "evidenceIds": []},
        {"layer": "template", "verdict": "unknown", "explanation": "尚无足够模板或提示词证据。", "evidenceIds": []},
        {"layer": "workflow", "verdict": "unknown", "explanation": "尚无足够工作流证据。", "evidenceIds": []},
        {"layer": "model", "verdict": "unknown", "explanation": "尚无足够模型能力证据。", "evidenceIds": []}
      ]
    }
  },
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
      "verification": "checks required to establish the effect",
      "candidateIds": []
    }
  ]
}
```

`presentation` is required for every newly emitted result and is optional only
when reading older persisted v1 reports. It owns the ten-second scan layer, not
new evidence: its facts, causal nodes, primary finding, and receipt IDs must
refer back to the same frozen inspection and findings as the detailed report.
Use `expectedStageCount: 0` when no authoritative expected-stage contract was
frozen; the projection must label that metric unavailable rather than claiming
that zero stages were expected. Do not decompose an error string into confirmed
causal steps unless separate frozen Evidence supports each step.

`presentation.failureAttribution` is required in every new result and optional
only while reading an older persisted v1 result. It is the plain-language
failure ownership decision:

```json
{
  "primaryLayer": "tool | skill | template | workflow | model | unknown",
  "summary": "plain-language attribution",
  "layers": [
    {"layer": "tool", "verdict": "primary | contributing | healthy | unknown | not_applicable", "explanation": "...", "evidenceIds": []},
    {"layer": "skill", "verdict": "primary | contributing | healthy | unknown | not_applicable", "explanation": "...", "evidenceIds": []},
    {"layer": "template", "verdict": "primary | contributing | healthy | unknown | not_applicable", "explanation": "...", "evidenceIds": []},
    {"layer": "workflow", "verdict": "primary | contributing | healthy | unknown | not_applicable", "explanation": "...", "evidenceIds": []},
    {"layer": "model", "verdict": "primary | contributing | healthy | unknown | not_applicable", "explanation": "...", "evidenceIds": []}
  ]
}
```

The five entries and their order are mandatory: `tool`, `skill`, `template`,
`workflow`, `model`. Emit at most one `primary`, and make `primaryLayer` name
that same entry; when no primary is defensible, use `primaryLayer: "unknown"`
and emit no primary verdict. `primary`, `contributing`, and `healthy` require
one or more frozen inspection Evidence IDs; `unknown` and `not_applicable`
may use an empty list. Every Evidence ID is checked against the frozen
inspection when the report is completed.

Tool receipts take precedence over outcome-based blame: if the receipt proves
the Tool effect worked, mark `tool` `healthy` even when the final result is
wrong. Do not blame model capability until inputs/outputs and Skill,
template/prompt, workflow, and Tool evidence are adequate to exclude those
layers. A model's error text or a plausible answer is not sufficient evidence.

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
report revisions. A repair-handoff authorization creates a Trace repair Session
with exactly:

- `mode: "coordinator"`
- `toolProfileVersion: "control-center-auto-approve-v1"`
- `executionMode: "full_trust"`
- `dangerousModeConfirmation: "ENABLE_FULL_TRUST"`
- `workspaceRoots: ["/"]`
- `toolAllowlistMode: "profile"`
- `projectContextEnabled: true`, `piSkillsEnabled: true`, and
  `codexSkillsEnabled: true`

The completed-report UI keeps one explicit confirmation explaining the
full-disk/all-tool automatic authority. This profile automatically approves
every Tool effect and does not require source-workspace equality or PAW
workspace-scope/approval hashes. Direct OS/TCC/Unix permissions may still be
the final boundary. The handoff itself is not proof that any mutation ran or
passed.
Persist the authorization receipt with
`writeAuthority: "auto_approved_full_trust"` for new handoffs. Historical
`"per_action_required"` and `"model_arbitrated_full_trust"` values remain
readable for older report revisions.

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
