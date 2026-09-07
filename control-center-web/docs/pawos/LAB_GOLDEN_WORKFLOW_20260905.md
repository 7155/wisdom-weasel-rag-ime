# Lab Golden workflow — implementation brief

## 整体设计入口

当前产品定位与前端设计以 [Agent Lab 产品整体设计](LAB_PRODUCT_DESIGN.md)为主入口：面向开发者与小团队，从描述/路径开始引导优化，交付 PAW App 及独立运行应用。原话和已定选择见 [UR-292–UR-297](requirements/PAWOS_REQUIREMENTS_292_297.md)。

本文件保留 Golden 原实施合同、历史检查与运行回执，不承担第二份整体设计，也不证明通用项目接入或 App 导出已经完成。

2026-09-07 的[通用工作台验收](LAB_GENERIC_WORKBENCH_ACCEPTANCE_20260907.md)新增两个真实项目、评审协议 v2、跨快照验证复用记录及 PAW/独立应用运行证据。两轮 B0/C1 正式比较均不能确认改善；C2 商品范围修整单独验收，不覆盖或重写下文历史结果。

## 用户需求账本 — 已记录的优化要求

[UR-284–UR-291](requirements/PAWOS_REQUIREMENTS_284_291.md) 记录 2026-09-06
最新澄清及 10 条逐字来源：Lab 要通过模型、提示词、Skill、工具、工作流及
Harness 的实际候选对照，为垂直任务选择成功率与成本合适的方案。先说明任务、
数据、工具和环境，再展示真实瓶颈、改动与验证；合理的完整上下文方案也是
需要检验的基线。RAG、企业知识库问答和运维排查各有执行与验收合同。

原有 Golden 四步和前端引导要求继续有效。下文的 `context_qa` / Prompt
执行适配器及历史运行回执只证明各自范围，不代表所有垂直工具、Skill、工作流
优化已完成。具体预算、质量门槛和收益等待任务与真实对照确认；本轮只记录需求。

## 原实施范围与收据

2026-09-06 的[面试展示稿](LAB_INTERVIEW_WALKTHROUGH_20260906.md)按业务任务、
执行环境、模型对照、失败与改动、复验与选择、工程边界组织现有历史证据。
可点击预览只用于讲述与交互设计，不代表真实 Lab 的完整前台路径已经接通。

Owner: current parent Session. User request, 2026-09-05: the App must complete
Agent drafting from real documents/history/failures with evidence, human review,
Judge calibration, and frozen automatic experiments. The user also renewed
permission to remove replaced incorrect code. No stable message ID was supplied.
The contract below is followed by scoped source and runtime acceptance receipts.

Production-flow research and the verified CloudOps scope are recorded in
[LAB_PRODUCTION_FLOW_RESEARCH_20260906.md](LAB_PRODUCTION_FLOW_RESEARCH_20260906.md).
It does not claim installed-product acceptance or a human-approved Golden set.

## Accepted experience

Extend the white Lab workspace with one preparation flow: 起草题目 → 审核标准 →
校准评审 → 冻结与实验. The existing experiment archive remains available. One
primary action per step; question list beside the selected question and evidence,
stacked on narrow windows. Sources can be real pasted document text, historical
task text or failure records, each with title and reference. No fabricated seed
data, automatic human approval, raw-JSON authoring requirement, or extra dialogs.

Agent drafts are editable. Human review and human answer labels are explicit
actions. Unknown Judge outcomes remain unknown. Editing standards or labels
invalidates calibration for future freezes. Frozen snapshots never change.
Experiments compare baseline and candidate on the same snapshot, use development
cases for tuning and touch holdout only after the candidate is fixed. Report
Golden changes separately from Agent improvements; these new datasets cannot
reuse historical scores as a same-case baseline.

## Owners and bounded work

- Store lane: new `rag_ime/agent_lab/golden.py`, migration 0190, focused store
  tests and the migration-head expectation only. Own persistence, validation,
  human-review/calibration/freeze rules and command idempotency.
- Execution lane: new `rag_ime/agent_lab/golden_execution.py` and focused tests.
  Own asynchronous jobs, Pi-backed draft/Judge/experiment calls and actual result
  evidence. Use an injected model-call callback; parent supplies the Pi adapter.
- UI lane: new `features/eval-lab/golden/` only, including TS contract, API hooks,
  four-step UI, styles and meaningful component tests. Parent supplies route IDs
  and integrates the actual Lab entry. Preserve DESIGN.md and shared primitives.
- Parent: service/transport routes, resident Pi callback, Lab entry integration,
  obsolete wizard removal after consumer checks, requirement index, checks and
  browser acceptance. No Browser/Ego edits, commits, pushes or installation.

All supporting lanes use Astra under the user's existing parallel-work request.
Each returns changed paths, focused test evidence and remaining boundaries; the
parent verifies integration. Source changes stay uninstalled until separately
validated. Existing dirty work must be preserved.

## Shared HTTP and data contract v1

GET pathId `agent.eval-lab.golden.get`, path `/api/agent/eval-lab/golden`, optional
query `suiteId`; response `{ok:true,items:GoldenSuite[],suite:GoldenSuite|null}`.
POST pathId `agent.eval-lab.golden.command`, path
`/api/agent/eval-lab/golden/command`, body
`{action,suiteId?,expectedRevision,clientRequestId,input}`. Return
`{ok:true,suite:GoldenSuite,job:GoldenJob|null,clientRequestId,replayed:boolean}`.
Validation errors 422, stale revision/request conflict 409, temporary service
errors 503; all include safe `{ok:false,code,message}`. An unknown network
outcome is retried only with the same complete command identity.

Actions and input:

- `create`: title, scenario, sources, targetCount (default 30); expectedRevision 0.
- `draft`: model (optional), using the suite's sources and requested count.
- `review_case`: caseId, question, taskType, answerable, requiredFacts, evidence,
  rubric, split, verdict (`approved`/`rejected`), note. Review is a human action.
- `label_sample`: caseId, sampleId, answer, humanVerdict (`pass`/`fail`/`uncertain`),
  humanNote. Changing labels resets the calibration.
- `judge_config`: judgeConfig.
- `calibrate`: no extra input, evaluates labeled development samples only.
- `freeze`: no extra input, requires reviewed cases in both splits and current
  passing calibration. Idempotently records an immutable snapshot.
- `experiment`: snapshotId, baseline ModelConfig, candidate ModelConfig,
  optimizePrompt boolean (default true), maxCandidates (1–3, default 1).
  Runs baseline/development, bounded prompt proposal and candidate/development,
  then one frozen baseline/candidate holdout comparison. General Tool/Skill code
  optimization remains in the existing Room experiment workflow; this first
  Golden execution adapter explicitly reports `context_qa` and prompt scope.
  The Lab setup now also records an explicit optimization target (`prompt`,
  `retrieval`, `tool`, `skill`, `model`, or `workflow`) alongside the layer. The
  dispatch contract contains only target-specific repair operators and planned
  counterfactual probes, so a Tool/Skill trial cannot be mistaken for a Prompt
  trial even before its real Room run begins.
- `cancel`: jobId. Actual Pi abort via the application, no fabricated completion.
- `resume`: jobId, resumes a persisted interrupted job, never blindly replays an
  unknown accepted model call. UI names the action 恢复任务. A failed draft with
  exactly one completed model receipt and unchanged source revision also exposes
  重新处理结果. It sets `reprocessOnly`: read and parse that exact completed output,
  with no Provider call even if the cache cannot be read.

`ModelConfig = {provider:string,model:string,thinkingLevel:string,prompt:string}`.
New suites capture the current configured primary model and thinking level;
later configuration edits do not change existing suites or replayed commands.
Model identifiers and thinking levels must be explicit at execution admission;
the selected Judge config is frozen and is not changed by candidate optimization.

`GoldenSuite = {schemaVersion:'rag-ime.agent-lab-golden-suite.v1',suiteId,title,
scenario,revision,targetCount,sources:Source[],cases:GoldenCase[],
judgeConfig:ModelConfig,calibration:Calibration|null,snapshot:Snapshot|null,
jobs:GoldenJob[],createdAtMs,updatedAtMs}`.

`Source = {sourceId,title,kind:'document'|'history'|'failure',uri,text}`.
`Evidence = {sourceId,quote}`; quote must occur in the referenced frozen source.
`GoldenCase = {caseId,question,taskType,answerable:boolean,requiredFacts:string[],
evidence:Evidence[],rubric:string[],split:'development'|'holdout',
review:{status:'pending'|'approved'|'rejected',note:string,reviewedAtMs:number|null},
samples:Sample[]}`.
`Sample = {sampleId,answer,category:'correct'|'incorrect'|'boundary',
humanVerdict:'pass'|'fail'|'uncertain'|null,humanNote:string}`.
Generated sample categories are intentions, never human labels.

`Calibration = {calibrationId,suiteRevision,judgeConfig,judgments:Judgment[],
metrics:{total,comparable,agreement, falsePasses,falseFails,uncertain},
ready:boolean,reasons:string[],createdAtMs}`.
`Judgment = {caseId,sampleId,verdict:'pass'|'fail'|'uncertain',reason:string,
evidence:Evidence[]}`. Calibration needs labeled positive, negative and boundary
examples, at least one human pass and fail, no false passes, no unknown Judge
verdicts and >=0.8 agreement on comparable labels; show small-sample limits.
Unknown human labels are reported but excluded from pass/fail denominator.

`Snapshot = {snapshotId,suiteId,version,sourceRevision,createdAtMs,
developmentCount,holdoutCount,judgeConfig}` is the public immutable identity;
the store privately retains the full source/case/rubric/calibration snapshot.

`GoldenJob = {jobId,kind:'draft'|'calibrate'|'experiment',state:'queued'|'running'|
'completed'|'failed'|'cancelled'|'interrupted',progress:string,sessionId:string,
error:string,result:object|null,canReprocess:boolean,reprocessOnly?:boolean,
createdAtMs,updatedAtMs}`. Agent claims do not
author these states: the worker records real Pi settlement and validated output.

## Store / execution seam

`AgentLabGoldenStore(db_path)` offers `read(suite_id='')`, `command(payload)`,
`job_input(job_id)` returning `{job,suite,snapshot:fullSnapshot|null,input}`, and
`update_job(job_id, patch)` for progress/binding. `finish_job(job_id,result)`
validates/ingests drafts or judgments and records experiment results atomically.
`recover_interrupted_jobs()` marks abandoned queued/running jobs interrupted.
Every async job freezes its relevant inputs. Old work cannot overwrite newer
reviewed revisions. Session/call checkpoint storage may be added by agreement.

`AgentLabGoldenApplication(store, complete, abort, completed_result?)` offers `read`, `command`,
`close`; starts bounded worker threads for async jobs. Injected
`complete(*,request_id,model,prompt,on_session,cancelled)` returns
`{text,sessionId,turnId,usage,receipt}`. It must use an ordinary Pi-owned session;
no provider loop is added. The Judge sees source, rubric and answer, never human
labels or which candidate is preferred. Optimizer receives development only.
Holdout answers receive the task and allowed source corpus, never reference
facts, rubric answers or calibration labels. Grade outcomes and report unknown
or runtime failures distinctly. Aggregate actual token/cost receipts only when
present; missing costs stay unavailable.

`completed_result(request_id, model)` is a read-only success-cache lookup. It
does not create a Session or read a Provider. Normal `complete` still binds both
the exact prompt and model. Reprocessing is the only path that may consume an
old successful output under a newer formatting parser. Draft normalization is
limited to a nonempty rubric string becoming one array item and the three
observed equivalent sample-category names; evidence and human labels are never
invented, and each formatting conversion is recorded.

Business answer cost, Judge overhead and optimization overhead have separate
scopes. Pi model-catalog prices are `estimatedCostUsd`, never billed actual cost.
Same-quality savings require comparable cost evidence; subgroup regressions
cannot be hidden by a better aggregate or lower cost. Failed settled calls retain
their reported usage. Unknown paid calls remain interrupted and are not resent.

## Acceptance and integration order

1. Store red/green: drafts are unapproved; human review persists; stale/duplicate
   commands cannot mutate twice; quote validation; edit invalidation; calibration
   false-pass rejection; immutable snapshot; terminal recovery.
2. Execution red/green: real callback invoked, hidden labels/holdout excluded from
   optimizer, correct frozen inputs shared between baseline/candidate, failed or
   uncertain model calls never produce success; cancel and reload recovery.
3. UI checks: source→draft→review→labels/calibration→freeze→experiment with real
   HTTP contract fixtures, uncertain-command recovery, keyboard and narrow layout.
4. Parent verifies routes/service plus build, then runs a real Pi drafting canary
   on an explicitly labeled acceptance suite. Human review is left to the human;
   fixture reviews prove mechanics only and are never production Golden approval.

Rollback: remove only this new flow and its entry; append-only migration history
and existing experiment evidence remain intact. No runtime installation is part
of this bounded slice. Update this document with actual checks and remaining
frontier before claiming delivery.

## Source and runtime receipts — 2026-09-05

- Removed the old `createEvaluationWizardRoom` entry and its participant/brief
  builders after checking their consumers. The new entry opens the persistent
  four-step app even if the historical archive read fails. Optimization Rooms
  and prior experiment records remain active consumers and were not deleted.
- The local source acceptance page is `http://127.0.0.1:5191/#/eval-lab?view=golden`.
  It uses actual source HTTP handlers, an isolated SQLite store on port 8791,
  and the installed managed Pi Runtime. Golden and scene-version routes use
  this local source owner; other app reads proxy the existing service. This is
  source acceptance, not a PAW installation receipt.
- Real source: repository `PROJECT.md`, supplied through the UI. Suite
  `golden:54d2317e-e303-4264-bcd1-bc422f324fa7` contains six real model-drafted
  questions, all **pending** human review; zero human answer labels were filled.
  Pi Session `agent:3add12d6-9fb8-4953-8efe-ec6e035616c1`, turn
  `38e8d71e-1d77-4bf3-9329-78212f289f6c` has a completed settlement. One durable
  model call exists before and after UI-triggered result reprocessing; no second
  model request was used to recover the six drafts.
- The first setup attempt had no admitted Pi turn: the isolated server had not
  loaded the configured Provider bundle. Recovery preserved the original call
  identity after correcting that acceptance-server setup. Refresh also restored
  the same running Session and turn.
- The real run exposed a separate settlement-read delay: Pi persisted completion
  at 04:06:45.345 UTC but the Python caller returned at 04:08:27.631 UTC. The
  adapter now makes bounded, at-most-five-second reads of the same authoritative
  Pi settlement within the original total deadline. The historical Host wake-up
  cause remains unproven; no Host or Pi Runtime source fix is claimed here.
- A second real, low-effort settlement canary completed in 3.215 seconds and
  returned 0.064 seconds after Pi persisted settlement. Session
  `agent:98e6529e-c63c-4358-bbab-4122a0870170`, turn
  `e7a54b71-4f52-4a4d-89f5-c2528d7b48ef`. This is one observed run, not a latency
  percentile or proof that the historical Host condition cannot recur.
- The separate suite `四步流程验收 · 合成数据` is explicitly synthetic: automated
  fixture reviews, labels and completion callbacks exercise all four steps and
  render calibration/experiment results. None of its scores or labels constitutes
  human review or real business-model improvement.

Final checks:

- `python3 -m unittest tests.test_agent_lab_golden tests.test_agent_lab_golden_execution tests.test_agent_lab_golden_pi tests.test_agent_lab_golden_routes`: **60 passed** (57.600 s).
- `node_modules/.bin/vitest run src/features/eval-lab/golden src/features/eval-lab/index.test.tsx --maxWorkers=1`: **55 passed** (27.32 s).
- Migration-head and append-only checks in `tests/test_database_migrations.py`:
  **23 passed**, verified by the Store lane after migration 0190 was frozen.
- `node_modules/.bin/tsc -b --pretty false` and the HTTP Vite production build
  passed. Existing large-chunk warnings remain; this is not a performance claim.
- Requirement ledger, bounded project harness, import boundaries, route
  ownership, scoped diff checks and Python compilation passed.
- One Impeccable detector pass on the new Golden directory and its entry returned
  no findings. Actual 933×867 desktop and 390×844 narrow views were inspected;
  completion now presents results before the collapsed next-run settings.
  Independent review found the two calibration fixes correct: unsaved labels
  are surfaced and block recalibration/continuation, while the standards
  disclosure includes required facts, rubric and evidence. The desktop
  calibration screenshot is retained at `.impeccable/review/golden/desktop-calibration.png`;
  the narrow calibration view was inspected live at 390×844, but the CUA
  screenshot bytes were not persisted as a repository artifact.

The user's linked [evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices)
were checked for the principle of calibrating automatic judgments with human
labels; the local numeric calibration threshold is an explicit product rule,
not an OpenAI benchmark or universal guarantee.

No commit, push or installation was performed for this Golden slice. General
Tool/Skill implementation optimization, external project execution, CI graders,
and a human-approved Enterprise RAG Golden benchmark remain beyond this bounded
context-QA and Prompt workflow.

## Replacement cleanup and integrated result checks — 2026-09-05

The user renewed the instruction: “修复了的话，把错误代码都删除”. Cleanup follows
the current consumer graph and retains executable regression coverage.

- Removed `experimentResultDisplayMetrics` and its nested rate/cost helpers
  from the Lab entry. `ExperimentWorkspaceResults` now calls the single
  `buildExperimentDisplayMetrics` projection for EnterpriseOps, Enterprise RAG,
  CloudOps, Memory Maintenance and the earlier retrieval aggregates.
- The already-replaced Lab wizard builders and `MemoryPipeline.tsx` have no
  production consumers. Their historical evidence and persistent migrations
  remain readable; they are not alternate implementations.
- Removed unused Room SVG edge/legend rules and the unused root-node animation
  selector from `paw-os-room-focus.css`. The current Sol mark still consumes
  `paw-room-focus-sol-breathe`, so that shared animation remains.
- Replaced the temporary whole-batch worker-exception cleanup in
  `agent_room_session_dispatch.py` with per-target typed failures. A successfully
  admitted peer retains its Pi turn; the failed peer alone receives a terminal
  failure. Admission reservations are released even if failure publication throws.
- Delegation test teardown now owns every coordinator/writer before removing
  its temporary database. Four previous two-second polling failures passed in
  isolation before this change; no production fix for those timeouts is claimed.
  Polling reads mechanical state without hydrating artifacts. The four focused
  tests passed three repetitions (12 executions); the timeout was not extended.

Fresh checks for this cleanup:

- Lab index/projection/result tests: **49 passed**.
- Room overview/live overview/style tests: **97 passed**.
- Room admission and partner-application backend tests: **17 passed**.
- TypeScript and production build passed; existing chunk-size warnings remain.
- Source and rebuilt bundles contain none of the removed production symbols or
  selectors. `git diff --check` passed.
- Interview ledger check passed: **40 metrics, 46 runs, 12 datasets**.
- The actual source UI was switched through all four result scenes. It showed
  EnterpriseOps `3/3, 31/31`; RAG `3/4 → 4/4, 7/9 → 9/9`; CloudOps
  `10/12 → 11/12, 98/99 → 130/130`; Memory `5/5, 4/4`, with their recorded API
  estimates. No business experiment was rerun for this display check.
- The synthetic calibration view was rechecked at 390×844. Its Golden region
  had `clientWidth=348` and `scrollWidth=348`; the screenshot showed a readable
  single-column layout. The temporary viewport was reset and the real RAG
  result view restored. No new human labels or approvals were submitted.
- The controlled full frontend run (`vitest run --maxWorkers=2`, no snapshot
  updates) completed in 7m16s: **266/267 files and 3010/3011 tests passed**;
  there were no unhandled exceptions. The sole failure was a stale route-test
  manifest. Its equality assertion remains; the five Golden/scene-version
  routes were reconciled with the frontend and backend owners. All **26 route
  tests passed** afterward. The original full-run exit code remains 1; the
  subsequent focused verification closes that failure without rewriting the
  original result. Reports: `/tmp/paw-frontend-cleanup-20260905/summary.txt`,
  `vitest-results.json` and `vitest.log`.
- The temporary source acceptance server was still forwarding scene-version
  reads to the earlier installed service. Those three scene routes now use the
  real source handlers and the same isolated Lab database. All Golden jobs were
  settled before the preview server was restarted; their data was retained.
- Actual UI application of the Enterprise RAG candidate produced revision 1
  (`gpt-5.6-luna`, Prompt-v4); browser reload retained it. Returning to the prior
  version produced revision 2 (`gpt-5.6-sol`, incumbent). The captured revision-1
  binding stayed on Luna after rollback. The receipt is
  `lab-recipe:2cd16865a6d145afb02770d469515a57`. This validates scene selection,
  persistence and rollback, not a new paid experiment or installed acceptance.

These changes are source-only. This cleanup does not change the installed PAW
version or complete the outstanding generic optimization/demo work.

## Four-scene execution controls, demo integration and further cleanup

The following source changes are integrated; they are not a completed generic
four-scene optimization controller or a new four-scene business result:

- EnterpriseOps, CloudOps and RAG runners read one bounded candidate Prompt
  file at admission and pass that actual text to their existing Pi execution.
  The file is limited to development/Validation. Reports distinguish the
  candidate identity, frozen controls and submitted Prompt from the baseline.
  EnterpriseOps' old profile-only promotion command rejects file candidates
  that it cannot reproduce. RAG reports a modified recipe as `parentSceneRecipe`
  rather than claiming it is still the exact saved recipe.
- RAG's `--judge-model` is now independent of the candidate model and frozen in
  run identity. Existing r6 receipts retain their historical Judge conditions;
  they are not retroactively relabeled as fixed-Judge trials. The Lab's Model
  target freezes Judge/Prompt/Tool/Skill settings for a model-cost comparison.
- Runtime cost export supports every model in the run-bound database. Actual
  Provider identities and settled usage must reconcile; missing costs stay
  unavailable. These are pricing estimates, not bills. RAG retains temporary
  execution evidence on failure or failed export. Resumed lanes cannot export
  a misleading cost receipt using only the new run's database.
- `AgentLabMemoryPiExecutor` reuses Golden's resident Pi execution, durable call
  identity, settlement, recovery and cancellation. Memory phase schemas validate
  the returned JSON. The script accepts an injected executor while its existing
  CLI remains a live consumer. The Pi factory is source-tested; no real Memory
  run or generic comparison through this adapter is claimed yet.
- Oshow's homepage and current four-scene panel consume the same bounded public
  export from the PAW experiment ledger. The RAG query selects RAG on the server
  response. Current and historical views share one scene selector. Old duplicate
  selectors, event synchronization and unused icon metadata were deleted; old
  second-approval-agent text was replaced with the current dispatch boundary.
  Historical failed runs remain evidence. The parent inspected the final RAG
  selection and quality/cost table in the real local page at port 4191.
- Deleted the unused `PublicActivityFeed` component, entry type, projection and
  planet helper plus its exclusive CSS and tests. The live `FxActivityStack`,
  `ActivitySummary` and `ReasoningActivitySummary` retain their tests. Removed
  Memory's unused `shortHash`, three unused Lab CSS selector groups, ten unused
  Lab display helpers and a Room `turnOrder` subscription whose value had no
  consumer. Consumer searches preceded deletion. Production state/evidence
  readers, historical receipts and append-only migrations remain in use.

The first real CloudOps trial of these controls failed before business scoring:
`cloudops-file-prompt-baseline-20260905-r1` completed five Luna/max Provider calls,
then three business Tool calls failed with `fetch failed`. No canonical submit
or Host score existed. The failed run's retained Runtime database reconciles to
an estimated `$0.00242404`; Provider requests completed, while the Agent turn
failed. This is not a business quality score.

A no-Provider canary reproduced the transport defect with the actual current
Runtime bundle: Pi's `undici.install()` replaced the one-time global fetch
wrapper and sent the private spool scheme to HTTP. The old assignment was
removed. The single spool router now adopts subsequent HTTP fetch assignments
as its HTTP delegate and ignores assignment of itself. Current bundle startup,
HTTP forwarding, repeated replacement/restore, timeout, abort and spool cleanup
passed. External Pi source and built Runtime files were not modified.

The replacement trial `cloudops-file-prompt-baseline-20260905-r2` completed
all three batches and released their gateway bindings. Host scoring reports
12/12 cases for AnswerCoverage, CA, FA, JRA and Top3JRA, with 142/142 successful
business Tool calls. The retained Runtime database and transcripts reconcile
95 completed Provider requests to an estimated `$0.3341084` (not a bill).
Elapsed time was 1,495,045 ms. This is a fresh current-Runtime validation run,
not a matched comparison proving an improvement over the older ledger winner.

The original r2 report also exposed duplicate Token accounting: its last
assistant message in each Session was added again after the Provider receipt.
The retained original reports 624,932 input / 7,193,088 cache-read / 64,242
output tokens; actual request receipts agree on 607,956 / 6,784,000 / 64,031.
The independent cost receipt already uses the actual requests. `_token_usage`
now gives Provider receipts exclusive ownership when present, while preserving
the older event fallback. A regression test includes completed and failed
requests plus duplicate final-message and turn usage. CloudOps/EnterpriseOps
and cost-export checks passed **63 tests** after the repair. The original r2
report is retained unchanged; no paid rerun or historical result relabeling was
used to conceal this projection defect. Future matched comparisons must account
for the changed runner identity.

Fresh validation for this slice:

- RAG candidate/recipe, mixed-model costs, Memory Pi/evaluation and showcase
  export: **64 tests passed**. Existing database ResourceWarnings were printed;
  they did not change the exit code and are not represented as production bugs.
- CloudOps/EnterpriseOps runners, promotion and optimizer Skill: **53 passed**.
- Spool/gateway/canary/CloudOps suite: **61 passed**; the parent independently
  reran both new transport tests against the current local bundle: **2 passed**.
- Model dispatch and experiment setup: **28 passed**. After removing the unused
  activity feed and styles, Agent activity, Memory timeline and Lab entry:
  **120 passed**. After removing the remaining Lab helpers and unused Room
  subscription, Lab/Room checks: **68 passed**. TypeScript and the final HTTP
  production build passed. A stricter unused-code check reported zero
  diagnostics in the four cleanup files; unrelated pre-existing diagnostics
  elsewhere are not presented as a passing repository-wide strict check.
  Neither source nor rebuilt output contains the removed component/selector
  names. The Room DOM tests retain the known JSDOM canvas-method warning.
- Oshow `CI=true npm test`: **17 passed**, including PAWOS/Story builds; focused
  UI **15 passed**, lint and TypeScript passed. The final public file inventory
  was rebuilt and `check_public_showcase.py` passed (**915 files, 12 Apps**).
  The PAW export checker confirmed all four current records match the ledger.
- Project harness, import boundaries, route ownership and interview ledger
  passed. The ledger still contains **40 metrics, 46 runs, 12 datasets**; no new
  business score was inserted to make the demo appear complete.

Outstanding: wire common scene admission, cancellation, result ingestion and
same-case quality/cost comparison into the App; complete real candidate reruns,
Tool/Skill implementation optimization and a human-reviewed Golden set. The
resume draft states implemented mechanisms separately from measured results;
the user's resume mother template is untouched. No commit, push, publication or
installation was performed.

## Next execution workboard — App-owned scene trials

UR-256/258 require real four-scene execution and measured improvements. The
existing Sandbox/Eval/Experiment stores retain immutable final receipts; they
cannot be mutated as live job status. A scene-trial application records only
experiment lifecycle and bindings, while the existing Pi runners keep actual
model/Tool execution. This is an additive execution owner until the replacement
is proven; the working Room optimization entry remains available.

Common contract, version `rag-ime.agent-lab-trial.v1`:

- `AgentLabTrialStore(db_path)`: durable idempotent admission, immutable public
  spec/private prepared input, queued/running/cancelling/completed/failed/
  cancelled/interrupted state, progress, actual Session/turn bindings and final
  result. `read` never claims/restarts work and never returns private input.
- `AgentLabTrialApplication(store, adapters, ...)`: registered adapter only;
  `start(client_request_id, scene_id, spec)`, `cancel(job_id)`, `read(job_id='')`,
  `run_job(job_id)` for controlled embedding/tests, and `close()`. Replay of the
  same request returns the original job; changed input conflicts. A failed wait
  or process restart must not create a new paid run.
- Adapter protocol: `prepare(spec, job_id)` is a read-only freeze and returns
  `{publicSpec, privateInput}`; `execute(privateInput, observer, cancelled)`
  returns the actual report mapping. `observer.progress(message)` and
  `observer.bind_session(session_id, turn_id='', cancel=None)` accept only
  observed execution facts. Cancel requests remain visible until execution and
  cleanup settle. Late results cannot rewrite a terminal cancelled job.
- `completed` means evaluation produced a report; its quality verdict is a
  separate result field. No statement by an optimizing Agent can set a passed
  quality gate. Initial adapters do not promise execution resume; interrupted
  jobs retain their bindings for exact inspection and future adapter recovery.

Ownership and verification:

1. Trial owner lane: new trial Store/Application and migration 0191 only,
   with admission replay/conflict, cancel, late completion, read/restart and
   private-input projection tests. Parent integrates service/routes/UI and real
   adapter. Do not change existing immutable receipt stores or migrations.
2. RAG owner lane: propagate cancellation and actual Session/turn observer
   through answer lanes, retries, Judges and cleanup. Tests must prove a stop
   aborts current execution and prevents subsequent lane/Judge admission.
3. Memory owner lane: separate CLI-only process effects from a callable
   evaluation body, retain full actual Pi request bindings privately and offer
   progress/cancel hooks between pipeline stages. Existing CLI behavior stays
   supported until App execution and comparisons are verified.
4. Parent: actual CloudOps adapter and current run evidence, common integration,
   source UI acceptance, result/cost ingestion and final two-axis review. Each
   subsequent adapter joins the same contract rather than creating another
   progress UI. Rollback removes only the unaccepted additive entry; retained
   run receipts and migration history are not rewritten.

## Continuation receipts — 2026-09-05 evening

The original JSONL, not the stale task preview, was read through its 16:39 CST
tail. The user subsequently completed PAW ChatGPT OAuth and authorized resuming
the interview measurements. Login receipts and later Room/UI requirements are
recorded in [Room experience](ROOM_EXPERIENCE_20260905.md#continued-session--2026-09-05-evening).

Source consistency and shared Trial execution:

- Agent snapshot reconciliation now restores local admissions before inferring
  missing replies. A successful later attempt resolves a turn while retaining
  the earlier failed assistant evidence; a later failure is still terminal.
- Once Pi accepts a Room turn, failure to write delivery-cursor/route metadata
  reports `projectionSync.state=pending` and preserves the accepted turn and
  idempotent receipt. It no longer fabricates dispatch failure or cancels Pi.
- Memory's synthetic Trial adapter is available by default only to an execution
  owner with private external artifact storage. Explicit adapter registries
  remain authoritative. RAG/CloudOps host assets and EnterpriseOps adapter still
  require integration; four scenes are not declared universally runnable.
- Trial UI retains start/cancel receipts after a failed follow-up GET and
  refuses stale-list rollback. Completed quality rejection, execution failure,
  cancellation, interruption and unavailable costs remain distinct.
- Focused verification: Agent/route/live-store 108 tests; Room admission 18;
  Trial backend and supporting Pi evaluation 111; Trial UI/Lab entry 57;
  OAuth 14. TypeScript and HTTP Vite build passed. The broader Agent suite had
  302 passes and one model-switch timeout; that unchanged test passed alone.
  This is not described as an all-green broad-suite run.

### New Memory Pi pair

- External root:
  `<PAW_STORAGE>/lab-candidates/memory-trial-pair-20260905-1819-r3`.
- Both trials use five fixed synthetic fixtures, `full-json-v1`, `standard-v1`,
  `max`, local hashing embeddings and Pi Session transport. Only Sol versus
  Luna is varied. The older CLI pair used `concise-json-v1`; its historical
  results remain separate.
- Baseline `lab-trial:02764c0929934acb9f51e29855810a9d` and candidate
  `lab-trial:a7f5cc0651ba4707bb59abfce766972b` both completed with quality `pass`:
  5 source/model decisions, 6 governed atoms with legal lineage, passing
  retrieval/abstention, and successful rollback plus cached replay.
- Actual DB events and retained transcripts reconcile four completed Provider
  requests, zero failed, two per model. The frozen Pi catalog reproduces the
  runtime estimates: Sol `$0.163425`, Luna `$0.0071846`, total `$0.1706096`.
  `reconciled-runtime-cost.json` contains the independent per-model receipt.
  These are estimates, not bills, personal-memory quality or held-out gains.
- Earlier harness attempts are retained: the first stopped in `prepared` before
  a turn because the standalone environment lacked a configured model; the
  second failed preflight before creating a service. No paid request was replayed
  to conceal either attempt. The successful harness explicitly selects the
  already verified built-in OAuth provider and leaves final model admission to Pi.
- Ledger/Experiment ingestion, visible source Trial acceptance and native
  installation are separate remaining boundaries at this receipt.


### Memory Pi pair ingested — 2026-09-05 evening

The new independent `memory.maintenance-pi-model-only-20260905-r3.v1` is now
registered and selected by the showcase. The original CLI pair remains unchanged.
The ledger contains 35 experiments, 41 metrics, 47 runs and 13 datasets. Runtime
usage reconciliation covers two requests per model, zero failures; priced usage
falls from $0.163425 to $0.0071846 (95.6037%), while tokens rise from 14450 to
15078. Quality gates pass before the cost comparison. `check_interview_metrics`,
`check_interview_agent_experiments`, exporter `--check` and six related Python
modules (64 tests) pass. These are source/read-through receipts; final native
installation is recorded in [the causal continuation](PAWOS_RELIABILITY_CONTINUATION_20260905.md).
