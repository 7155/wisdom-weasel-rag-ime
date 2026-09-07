# Existing Lab scenarios in the project workbench

## Request and chosen scope

> 相当于我们现在已经测完了四个垂直场景，你把它迁移进去，或者我们就重新测也行，看一下怎么做。

The current Session owns this migration, integration, and verification. Existing
four-scenario experiments take priority over searching for another dataset.
Preserve the unfinished WixQA resource project as additional RAG work. Existing
results are imported as historical evidence; importing does not re-execute,
rescore, rewrite old decisions, or prove a new model improvement.

## Work and acceptance

| Work | Owner / dependency | Operability check | Requirement check | Rollback |
| --- | --- | --- | --- | --- |
| Preserve existing records in four projects | Project store + existing experiment projection; first | Atomic import/replay, source-change rejection, exact snapshot equality, no Pi/model calls | Every existing scenario retains baseline, candidate, rejected history, metric denominators, source versions and claims | Original ledger and prior artifact revisions remain unchanged |
| Import through the actual frontend | Project workbench; after import contract | Visible import, open existing project, refresh and duplicate-click behavior | Four projects show inspectable experiment overview, metric comparison, changes and original records | Existing projects/materials remain intact |
| Continue execution through existing owners | Trial service and existing scene adapters | Show current registry availability and retain new-job identity | Historical migration and a newly executed experiment remain distinguishable | No raw Gold mounted into project Agent context; no replay of historical executions |

Existing sources: `eval/interview-metrics/agent-experiments.v1.json`, referenced
`runs/` receipts, `EvalLabProjection`, and `AgentLabExperimentStore`. The source
checker passes. Current source projection contains 34 experiment records in the
requested four groups: EnterpriseOps 6, Enterprise RAG 10, CloudOps 9, Memory 9.
The separate Trace repair record is outside the user's four-scenario request.

Raw datasets and historical execution artifacts remain with their existing
owners in the sibling research workspace and local evaluation directories.
They are not concatenated into model context or copied into a fake completed
Trial. The imported snapshot is the public evidence projection, including
original dataset identities, hashes, frozen controls and source references.

Current candidate runtime registry observed before migration: `memory` and
`knowledge-resource`. RAG and CloudOps adapters exist in source but their host
assets are not registered in this candidate. EnterpriseOps has its original
CLI/harness, not a registered generic Trial adapter. Their historical evidence
is usable without re-running; these execution connections need separate fresh
verification before claiming all four can be rerun in the new workbench.

## Verification receipts

Foreground imports completed through the visible candidate frontend. Four new
projects contain four artifacts each: experiment overview, original metric
comparison, changes/conclusions, and the immutable original evidence snapshot.
All 34 imported records compare equal to the source EvalLabProjection, including
its RAG optimization-evidence extension. The three pre-existing projects remain.
No imported project created a Guide Session and the Trial count remains four
(the pre-existing Wix intake/index attempts); the import called no model.

Browser checks covered opening original metrics, current versus rejected
history, refresh persistence, all four import options changing to “open imported
project”, CloudOps showing unavailable execution, and Memory exposing its
registered run action. No paid rerun was started. The candidate backend was
restarted with all imported data retained. Source tests: first 24 backend tests,
17 frontend tests, followed by 10 focused backend tests including the new
scene-scoped Guide read. Typecheck and production HTTP build passed. Detailed
local evidence is `acceptance/history-migration-receipt.json` under the candidate
artifact directory. Import boundaries, route ownership and source-map checks
are separate source checks, not native-installation evidence.

The original WixQA full index still needs diagnosis: after fixing title path
separators, a subsequent full index failed after 4,546 documents. Its failed
receipt and partial sandbox remain; no completed Wix retrieval or answer
metric is claimed. That task is preserved as additional RAG work.

No commit, push, native installation, or paid four-scenario rerun was performed.
The next execution frontier is registering original RAG/CloudOps host assets
and adapting the existing EnterpriseOps runner, then making bounded new runs
through each project. Historical import is complete; full four-scene rerun
acceptance is not.
