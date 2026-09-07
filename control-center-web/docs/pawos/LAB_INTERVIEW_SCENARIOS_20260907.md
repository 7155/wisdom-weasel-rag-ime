# Four Lab scenarios: materials, execution and interview demonstration

## Current request

User-direct request, 2026-09-07, message `583333885`:

> 要补的是各场景的真实资料、工具和执行器绑定，再逐个完成前台实验与导出。本次新增的召回、思考、输出反馈可以直接复用。我主要是面试展示用

Follow-up, message `671924853`:

> 把材料数据补齐

This continues the [four-scenario migration](LAB_EXISTING_SCENES_MIGRATION_20260907.md).
The 34 original experiments remain historical receipts. The present work first
restores actual materials, then connects their execution owners and verifies new
frontend runs and exports. New runs use distinct identities. Existing validation
and held-out results are not relabeled as fresh or unbiased results.

## Bounded work and ownership

The current Session owns integration, frontend acceptance and the final result.
Independent material preparation uses the `orchestrate-session` workflow;
children return evidence and proposed host configuration, not acceptance claims.
Live ownership and execution status come from Runtime, not this document.

| Work | Accountable owner / supporting scope | Operability acceptance | Requirement acceptance | Dependency / rollback |
| --- | --- | --- | --- | --- |
| Restore CloudOps materials | Parent; CloudOps material child | Source bytes, hashes, blind/host scoring split, actual tool inputs parse | An inspectable incident can be traced through observations to its scoring rule; origin and limitations explicit | Original source files retained; new bundle removable |
| Restore EnterpriseOps and RAG materials | Parent; enterprise material child | Original task/DB fixtures and corpus/qrels/retrieval assets present and matched | Business task, tool state and evidence are sufficient for a bounded demonstration; Gold stays host-only | Original source and historical runs retained |
| Restore Memory materials and connect all project materials | Parent | Canonical fixture equality, input/label split, UI import and refresh persist | Every project shows real material snapshots, tools and provenance; controlled fixtures clearly labeled | Append-only project material versions; no personal database exported |
| Bind original executors | Parent | Host registration and focused adapter checks; Pi owns model/tool execution | Each displayed run belongs to the intended data, model, method and scorer | Explicit candidate-only configuration; native service unchanged |
| Frontend experiments and exports | Parent | New run receipts, reusable feedback, prepared/active App and verified archive | Small reproducible interview walkthrough with quality denominators, rejected candidates and evidence boundaries | Original 34 records and prior Apps preserved |

Integration order: restore and validate materials; import through the frontend;
register bounded executors; execute and inspect each new run; prepare and verify
scenario Apps. Completion requires both operation and requirement acceptance.
The current executable frontier is material restoration. No new experiment or
four-scenario App completion is asserted by this plan.

## Data and demonstration policy

- Use original available benchmark material before seeking replacements. A
  benchmark's controlled workload is not a production customer incident.
- Keep complete usable bytes with a manifest and provenance; a historical metric
  table alone is not an input dataset.
- Agent-visible material includes task inputs and tool contracts. Host labels,
  expected outcomes and evaluation-only evidence remain separate.
- Use small development demonstrations and preserve original split identities.
  Previously inspected validation is candidate-aware. Do not tune on held-out.
- Keep actual model usage separate from price estimates and billing. Luna max
  remains the selected model for the new Lab model runs unless the user changes it.
- Reuse the portable App progress template, with actual retrieval, public model
  activity, partial output and terminal receipts. Tool-dependent exports must
  preserve a real tool owner or state their recorded-replay boundary explicitly.

## Receipts

Material manifests and local evidence are stored in the candidate's
`interview-materials/` directory. Detailed receipts are added after verification;
this document does not substitute for live project or executor state.

## Subsequent direct requirements and selected direction

The user supplied screenshots of Songguo App v11 and said:

> 还有导出的app，对话也要精致呀，就像正式产品，有进度和动画，就像能够perplext一样，深度研究或者调研这些都有告知

> 当前非常粗糙

This adds a shared producer/template requirement: a polished conversation,
readable streamed answers, expandable actual work, citations, animation tied to
real activity, Stop, history, and genuine follow-up context. The user specifically
showed the oversized form and equal-sized answer cards as rejected examples.

The user then asked to prefer real data, inspect the `sgg` folder, and accepted
official brand material as an initial option. Inspection found course/source
archives in the volume's `sgg` folder; the repository SGG ledger is explicitly a
fixture. Neither was verified as real company after-sales data. Public policy
and actual customer-operation records remain different data classes.

The subsequent selection was:

> Earth Engine

> 这样做的话，有场景吗，就是有地理需求就能问，然后我们有地理项目，就在git下面

> 有场景吗需求场景，企业需求场景，科研需求场景

> git路径下面有一个谷歌项目，也是我们的

The user corrected the proposed scientific first scenario:

> 我要企业能够用的，例如横向

The selected product direction is therefore enterprise-use geospatial work,
grounded in official Earth Engine material and the existing ScoutPi Workbench
repository. The parent's proposed first scope is season-consistent vegetation
change monitoring for a supplied enterprise AOI. This is a satellite proxy;
it does not itself certify ecological restoration or regulatory acceptance.
Google documentation provides knowledge, while reviewed ScoutPi workers own
actual calculations and exports. This direction does not erase the four
existing scenario materials or authorize treating their fixtures as real
production customer records.

### Observed material and interface progress

- Memory: complete canonical five-case controlled fixture, hash equal to the
  retained Pi pair receipt. Six Agent-visible input/query/schema/contract files
  (14,210 bytes) were imported through the frontend into the existing project.
  Host labels and historical results remain outside its model input materials.
- CloudOps: supporting preparation returned a complete 12-case Validation
  execution bundle and a 13-file project subset. Parent integration remains.
- EnterpriseOps/RAG: material bundles returned; EnterpriseOps needs its original
  task and initial-state bytes to close fresh-execution completeness. RAG is a
  synthetic enterprise-document benchmark, not verified real company records.
- ScoutPi: source and local metadata audit found the typed Earth Engine pipeline,
  installed Earth Engine/geedim dependencies and prior July live artifacts.
  No current service or cloud execution acceptance follows from those old files.
- Shared conversational starter, App-local Stop bridge, supplied-document
  progress and follow-up contract are implemented in source. Fourteen frontend
  tests, 26 App/backend tests and TypeScript checking passed. Candidate build,
  foreground checks and immutable export verification are still required.

## Earth Engine full-flow continuation (2026-09-07)

The subsequent user directives select enterprise geospatial consulting, redo ScoutPi Spatial, and require one page with conversation on the left and map/story on the right. The user explicitly asks to retain the failures as Lab tuning cases and record the bugs. [The case ledger](LAB_EARTH_ENGINE_BUG_CASES_20260907.md) preserves source messages, reproduction, changes, verification and open boundaries. The downloaded corpus, live Earth Engine output, candidate App packages and retrieval trials are separate evidence classes. Full answer tuning remains pending a compatible Luna channel.


### Earth Engine candidate v7 result (2026-09-07, 19:43 local)

The complete bounded documentation snapshot is now imported (3139 deduplicated bodies). Lab retains the failed URL metric job, old 1200/160 baseline, query candidates and new 8000/320 index. The final index has 5242 chunks. Five development cases and one derived holdout have source Recall@12 of 1.0, with MRR 0.7333 and 0.25 respectively. Actual final App context passes 11 content-presence checks. The original long-query fixed-page qrels only reach 0.5 on this index; alternative tutorial evidence supports the date boundary. No references were relabeled to improve the score.

Six original questions have Agent-attributed review and 15 edited Agent-attributed calibration samples in suite `golden:d6bc6552-d9e3-4ca0-b5a6-c80dca42ab8c`, revision 23. Luna Max is configured, but model calibration, answer comparison and a frozen answer-quality snapshot are not complete. This is known-source development evidence, not independent human Gold or a blind holdout.

Real Earth Engine outputs include NDVI 0.34474720384639734 (2024) and 0.3847049619317028 (2025), CSV, GeoTIFF, a local analysis and an evidence-bound story. Image count and valid-pixel coverage remain absent. Final v7 UI and portable package have been verified from /tmp, including desktop/mobile and the three reviewed source/status corrections. The 10-case ledger links reproduction, repair, checks and residuals. No model-answer, native installation, commit, push or deployment acceptance is inferred.


### Earth 企业场景：地理研判台 v8（2026-09-07 追加）

用户消息 `39634204` 要求名称、App 与前端重做；`110776463` 明确选择“地理研判台”。已在候选 PAW 启用 v8，统一标题与蓝灰白底，修复内嵌内容未占满窗口（CSS1012×852，两个 iframe 与 pane 均685px）。独立版1280×720与390×844截图复查 SHIP，无必要阻断项；原生安装仍未验收。

质量扩展已闭环：源作业 `earth_20260907120250_9dff6f77` 与独立包作业 `earth_20260907122454_b7c376f9` 的年度JSON完全一致，2024/2025入选62/74景，均49729/49729网格有效覆盖，10m EPSG4326，与NDVI均值共用网格且不自动粗化。缺失值、零、空集合和掩膜等6项聚焦检查通过。100%是最终合成覆盖率，不是每景无云率或修复验收通过；空间置信区间和因果对照仍缺。

新增质量作业曾遮住原GeoTIFF；现按故事关联的同计划已完成作业补充地图文件，保留真实下载URL并排除其他计划与未完成任务。独立包为 Geo-Analysis-Workbench-20260907-v8-final.zip，509项文件哈希/大小和ZIP CRC通过；原历史仍保留。Lab案例现11项，案例artifact v3、交付结果artifact v2。Luna Max仍无法调用，6道原题与15个Agent标签仅是准备状态，没有回答模型校准或Prompt优化成绩。资料问答当前不能自动操作浏览器或执行空间任务。
