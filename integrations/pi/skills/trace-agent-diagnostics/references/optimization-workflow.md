# Optimization And Distillation

Use the live `trace_diagnostics` Tool with `op: inspect|read|command`. All
`read` and `command` calls require the current `reportId`; commands also need
a stable `clientRequestId`. The service derives the caller Session. It rejects
another report's resources, out-of-focus changes and model adoption commands.
`input` is a nested object for the named command; do not add arbitrary result
fields or installation receipts.

## Read What Is Already Known

Start with `{op:"read",reportId}`. It returns the frozen report, bounded
experience summaries and actual Lab jobs. Search with `query`; read a selected
body with `patternId`, optional `revision` and `offset`. Historical pattern
references go into a proposal's `historicalPatternRefs`, never its current
`evidenceIds`.

A report automatically preserves its evidence-linked observations and
hypotheses after completion. Actual comparisons separately preserve accepted,
rejected, not-run and interrupted attempts. These artifacts are versioned in
the optimization project and survive a version being rejected or rolled back.
Use `save_pattern` only for a useful cross-case synthesis beyond that automatic
record. Its `input` is `{pattern, patternId?, expectedPatternRevision?,
expectedRevision?}`; the pattern contains `title`, `summary`, `scope`,
`symptoms`, `observations:[{statement,evidenceIds}]` and optional
`hypotheses:[{statement,evidenceIds,uncertainty}]`.

## Freeze A Concrete Candidate

1. Read the active component. Prepare a changed copy in a separate directory
   inside the bound source project. A Tool candidate includes real code and
   interface/error behavior; a description alone is not an implementation.
2. Call `command:"register_version"` twice, for baseline and candidate. Each
   input is `{targetKind,targetRef,sourcePath,entryPath?,destinationPath?}`.
   Both registrations identify the same `targetKind`, `targetRef` and intended
   destination. `targetKind` is `tool|skill|prompt|workflow`. The service copies
   the bytes and returns `versionRef`; it never trusts a model-supplied hash.
   A package directory needs `package.json`; a bare Skill directory should set
   `entryPath:"SKILL.md"`. Package installation uses a real Pi Package.
3. Prepare a representative task check. The local task adapter accepts a JSON
   plan at `sourcePath` via `command:"register_plan"`:

   ```json
   {
     "title": "Capitalization cases",
     "timeoutSeconds": 10,
     "cases": [
       {
         "caseId": "uppercase",
         "command": ["python3", "{version}/tool.py"],
         "input": {"word": "hello"},
         "expectedStdout": "HELLO"
       }
     ]
   }
   ```

   Each case runs against a fresh copy of the registered version. Its input is
   canonical JSON in `PAW_TRACE_INPUT`. The Host checks actual exit status and
   exact trimmed stdout, records Trace and ground-truth Eval, and requires all
   cases to pass. The plan and expected outputs are frozen before admission.
   Select representative checks from the intended behavior; never tune the
   expected output simply to admit a candidate. This adapter proves local
   fixture behavior, not unseen tasks or model-following of a Skill.
4. Call `command:"prepare_candidate"` with `{parentVersionRef,
   candidateVersionRef,planRef,summary,expectedEffect,evidenceIds,findingIds?,
   historicalPatternRefs?}`. It returns a real `candidateId` and actual diff.
   During report generation `findingIds` may be empty. Link the resulting ID
   from the final finding's `candidateIds`; the report projects both directions.
5. Call `command:"run_candidate"` with top-level `candidateId`, then `op:read`
   for the two Lab jobs and comparison. `command:"cancel_candidate"` stops
   both jobs; cancelled or incomplete runs never count as improvement. Reuse
   the same request ID for a retry of the same action. A new attempt requires
   a new ID. Do not submit scores or fabricate Trace/Eval/application receipts.

The fixed failure-only replay remains a separate protocol. A declared
intervention comparison may change its target factor, but must preserve task
inputs, evaluator, quality requirements, permissions and non-target component
versions. Cost is unknown unless real complete usage receipts exist. An
executed candidate can still be rejected for regression or lack of improvement.

## Test Through Pi

For Skill behavior, prompt content or a bounded Pi workflow, register a plan
with `executionKind:"pi_session"` instead of a command plan. Read the configured
provider/model identity first; do not invent a model name. The plan contains
`model:{provider,model,thinkingLevel}`, `allowedTools` (only `workspace_read`
and `workspace_search`), `cases:[{caseId,input,expectedText}]`, `timeoutSeconds`
(1–900) and `maxTaskTurns` (1–64, covering both baseline and candidate).

`expectedText` is Host-only ground truth and is not copied to the tested
Session's prompt or workspace. The Host checks exact trimmed final text, so
choose cases with an unambiguous expected answer. `maxTaskTurns` bounds admitted
Pi task turns across both executions, not the number of internal Provider
requests. Pi continues to own model/Tool loops, Stop and settlement; the
report records available actual request/usage evidence separately.

For a Skill, `entryPath` identifies its `SKILL.md`, and baseline/candidate must
keep the same trigger name. A private durable evaluation binding supplies the
candidate Skill path to a Host that advertises support. Copying a file into a
workspace does not itself load a Skill. Comparison authority requires the
actual `skill_load` content receipt, model, tool schemas and prompt composition.
An older Host or missing receipt cannot become a verified improvement.

For a prompt, the registered text becomes only that evaluation Session's
system instructions. For a workflow, register JSON
`{"steps":[{"instruction":"one bounded step"}]}` with 1–4 steps; each step
uses the same Pi Session, and the final output is evaluated. Tool/model changes
are not supported by this Pi adapter. Tool functions can use the local adapter,
then the real Package installation owner. Set `compareCost:true` in
`prepare_candidate` only when cost is part of the desired comparison; incomplete
cost receipts remain unknown and cannot justify adoption.

The user chooses **keep original / install / replace / apply** in the report.
Only available actions backed by a real owning resource are shown. The package
bridge uses the existing Pi validation, preview and application service; a
single file application checks that the active file still matches baseline.
An interrupted installation stays uncertain and is not repeated. Existing
Sessions retain their loaded version; newly installed resources take effect
according to Pi's normal resource lifecycle.

## Distill Several Conversations

For `intent.mode:distill`, call `command:"prepare_distillation"` first. It
returns a bounded packet containing each selected source's intent, steps,
terminal evidence and source statements, a real Skill/Tool capability catalog,
historical attempts and limitations. An assistant saying it finished is a
statement, not a successful task receipt.

Then call `command:"save_distillation"` with:

```json
{
  "proposals": [{
    "suggestionId": "suggestion:one",
    "outcome": "experience_only",
    "title": "A reusable recovery pattern",
    "reason": "Explain the repeated evidence and applicability",
    "evidenceIds": ["an ID present in the returned source packet"],
    "capabilityNeeds": [],
    "existingCapabilityIds": [],
    "proposedChange": ""
  }]
}
```

Outcomes are `update_existing|new_skill|new_tool|experience_only|no_change`.
New capabilities need explicit missing capability keys and proposed content.
Existing matches point to exact catalog IDs. The Host checks source bindings,
catalog coverage and duplicate declarations; it may resolve a claimed new
capability to updating or reusing an existing one. The saved result is the
report's `distillation` projection; do not add it to the final diagnostic JSON.
If concrete candidates were already registered, `save_distillation.input` may
also contain `candidateBindings:{"suggestion:one":["returned candidateId"]}`.
Only IDs from this report are accepted. The initial distillation is immutable;
refine its interpretation in a new report instead of rewriting the source.

A distillation suggestion is still a draft. Create concrete source files and
use the candidate path above when executable validation is possible. Include
trigger, inputs, outputs, useful steps, exceptions and recovery in a Skill;
include real implementation, registration and error tests in a Tool. Distilled
conversations are development material. Original-case replay only demonstrates
coverage of those cases; reserve separate tasks for generalization claims.

## Human Reading Contract

The App and exported HTML share a report model: purpose and scope, observed
problems, Agent explanation, concrete changes, paired validation and adoption.
Keep source facts, model hypotheses and Host results separate. Write short
plain-language conclusions and connect findings to candidate IDs. Report
percentages only with measured denominators. The App owns font, spacing,
charts and export layout; do not produce executable HTML or invent visual
metrics in the Skill output.
