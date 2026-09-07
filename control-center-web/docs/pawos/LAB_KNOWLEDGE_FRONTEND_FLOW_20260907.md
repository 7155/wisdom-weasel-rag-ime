# Lab Knowledge frontend flow

This work extends the generic project workbench with an optional Knowledge
resource. It does not replace the project Agent or require every project to use
RAG. Owner: current Lab implementation Session. Source request: current user
conversation, 2026-09-07, following the WixQA introduction.

## User requirements

> 所以我们找一个大概比较大的知识库，然后从资料整理到就走完全流程，我们在前端 进行就不需要你在后端，就你需要在后端把所有代码流程写好，并且告诉我是怎么做的。然后我们就在前端调，这样子我们才算真的走通，反正最后都是要在前端使用和体验。到时候你就在前端，比如说这个文件夹怎么引入，或者这个知识库下载了怎么加入，然后评测级它 有有事怎么处理？没有事怎么处理？

The last clause is interpreted as evaluation-dataset-present versus absent.
The preceding requirement connects the existing Knowledge owner to sandboxed
chunking/index/retrieval optimization, followed by prompt and workflow changes.

## Implementation and acceptance

| Item | Owner and seams | Runs correctly | Meets user requirement | Dependency / rollback |
| --- | --- | --- | --- | --- |
| Import and inspect a real corpus | Lab resource composition; KnowledgeLibraryService owns parse/chunk/index/search | Idempotent background jobs, bounded source reads, interruption/retry, stable source IDs, immutable corpus/index generations | Frontend imports a downloaded JSONL or document folder, shows actual document/chunk counts and retrieved excerpts | First; retain previous generations and unrelated working changes |
| Separate evaluation data and compare retrieval | Lab dataset/evaluation composition | Reference joins validated; identical questions/shared gold documents remain together; every planned case is counted | Existing question/answer data retains originals; missing data leads to reviewed drafts, not invented real tickets; compare profiles against fixed splits | Corpus; selection retains explicit generation and comparison receipts |
| Answer and prompt evaluation | Optional golden.knowledge_qa binding; existing Golden jobs and Pi own execution | Solver receives query-only retrieved corpus excerpts; Judge alone receives references; immutable Knowledge binding survives later resource changes | Frontend moves from Knowledge experiment to existing standards/review/calibration/experiment controls | Indexed generation; old context_qa remains available |
| Frontend acceptance and explanation | Current Session integrates source, checks, candidate build and browser evidence | Focused backend/frontend tests, type/build, real browser interactions | A user can repeat the import/search/evaluation path without backend scripts; model costs and manual-review boundaries remain explicit | Prior items; candidate build only, no commit/push/native installation |

## Operating defaults

- Start with WixQA's public English knowledge corpus and ExpertWritten questions;
  record pinned source revision and local hashes. Do not claim recent customer
  data, contamination-free evaluation, or an official development/holdout split.
- Use a project-owned sandbox over the existing Knowledge implementation.
  Existing Knowledge bases are read through their owner when selected; source
  changes never mutate the connected base.
- Lexical retrieval is available without a model. Semantic embedding requires a
  real configured provider and a new index generation; no hashing-vector quality
  claim. Full-corpus concatenation is not an allowed solver path.
- Retrieval experiments use all applicable imported cases. Answer experiments
  expose a smaller, explicitly selected case budget before any Pi calls.
- Current implementation and foreground evidence will be appended here after
  checks. This plan is not a running-state or completion receipt.

## User correction during foreground acceptance

> 正常的不会有这个吧，得用户自己下载

WixQA is only the dataset used for this acceptance run. The generic product has
no dataset-specific download action. Users download their files at the source,
then import the corpus and evaluation set separately, or connect an existing
Knowledge base. Removed the temporary Wix downloader from frontend and backend;
the failed historical Trial receipt remains readable.

## First real-corpus checks, 2026-09-07

The user subsequently asked whether these datasets are suitable for interview
demonstration and what vertical scenarios currently exist. WixQA is the first
customer-support/RAG demonstration; other dataset suggestions are references,
not proof that their execution environments have been connected.

Pinned Wix revision: `d4fc7c3983733e8d65e06c7752926608c47a89e9`. Downloaded
corpus: 53,744,739 bytes, SHA-256
`af68c29c275b076718ee52cd56eb3eb90330fbdb1c78ea417fa517c744919b2e`;
verified against the official revision's LFS object metadata. Its README and
actual file both have 6,222 articles (newer dataset descriptions say 6,221).
ExpertWritten contains 200 distinct questions: 148 reference one article, 46
reference two, and six reference three. Every cited article ID exists in the
pinned corpus. Original files are retained in the user's download directory;
only UI upload/import actions populated this Lab project.

Foreground import completed with 6,222 documents. First full indexing failed
because article 102 has `Delivery/Pickup` in its title: the composition passed
this title directly as a plain filename to RagBenchmarkSandbox. A focused
regression reproduced the failure. The adapter now normalizes filename path
separators while retaining the original source title; all 12 Knowledge tests
pass, including retrieval of the original title. Full indexing has been
restarted through the UI. No completed retrieval or answer metric is claimed
in this checkpoint.


## Exact-content duplicate repair

The second full indexing attempt stopped before document 4,547 was inserted.
Inspection found a single exact-body duplicate pair among the 6,222 source IDs;
the existing Knowledge store correctly rejects duplicate byte hashes in one
base. The Lab adapter now indexes 6,221 distinct bodies while preserving all
6,222 original source IDs, titles and URLs in the immutable corpus. A compact
alias mapping records the duplicate relation. No text was altered to bypass
Knowledge deduplication.

The same exact-content identity is used for derived split families, retrieval
relevance and Golden evidence. Original reference IDs remain unchanged in the
imported dataset. Duplicate aliases therefore neither split equivalent sources
across development/holdout nor inflate the relevance denominator. Search
receipts expose aliases when a duplicate source is retrieved.

Validation: the two new regressions first failed (separate families and failed
index), then passed. All 14 Knowledge tests, 47 Golden/history/Trial tests and
five Knowledge frontend tests passed. TypeScript and production HTTP build
passed; import boundaries, route ownership, project harness and diff whitespace
checks passed. The next complete generation was started through the visible
frontend; completion and metrics must be recorded separately below.


## Label provenance during delegated frontend acceptance

This run is operated by the assistant at the user's request. Case review and
sample annotation now expose user-versus-Agent provenance in the existing
Golden workflow. Saved labels retain the compatible `humanVerdict` field, plus
an explicit `labelAuthor`; review records retain `author`. Draft-model output
still cannot set accepted review or label values. Calibration records author
counts and distinguishes Agent-assisted comparisons from independent human
reference validation. Existing unlabeled provenance remains unrecorded; old
snapshots are not rewritten. The numerical coverage, false-pass, uncertainty
and agreement requirements are unchanged.

Checks for this change: 68 Knowledge/Golden backend tests and 40 existing
Golden/Knowledge frontend tests passed; the added frontend provenance test
checks the actual selector, outgoing author field and honest label wording.


## Foreground results and current boundary

All operations below were admitted through the visible Lab UI. Read-only API
captures preserve the resulting receipts; no backend seeding or metric-writing
script created these results.

- Corpus: 6,222 source records, 6,221 exact-body identities.
- Completed index: `lab-trial:cf368d2d1fbb426383cae79e60930760`, Markdown
  1,200 characters with 160 overlap, 17,734 chunks, lexical only.
- Imported ExpertWritten: all 200 original questions with valid source joins;
  derived split 131 development / 69 holdout.

| Configuration | Split | Scored / planned | Recall@K | MRR | nDCG@K |
| --- | --- | --- | --- | --- | --- |
| K=10 | Development | 131 / 131 | 39.57% | 0.2396 | 26.38% |
| K=20 | Development | 131 / 131 | 53.31% | 0.2503 | 30.38% |
| K=20, fixed before check | Holdout, first use | 69 / 69 | 42.51% | 0.2170 | 25.98% |

This comparison changes candidate count; it does not prove a semantic model
improvement or an answer-quality gain. No answering model was called during
retrieval evaluation. Embedding is unconfigured, not simulated.

The UI then created `golden:c0c9fe71-5116-4426-8ed0-e6ae5d82b5d8` with the full
index and a stable four-question sample (one development, three holdout).
All four reviews explicitly record Agent authorship. Two scoring standards
were edited because the linked source did not directly support a named plan
requirement or the exact Search Console button sequence. Original questions,
reference answers and source IDs remain unchanged in the imported dataset.
This is a curated demonstration subset, not an official WixQA benchmark score.

Three edited/diagnostic development examples carry Agent labels. Terra's
initial three-example calibration completed with 100% agreement and no false
passes, false fails or uncertain judgments. The user then requested:

> 用luan max，这个便宜和智商可以的

The UI was changed to `gpt-5.6-luna` with `max` and saved as standard revision 9;
the old model's calibration was invalidated. Luna recalibration failed with a
provider `404 model_not_found`: no account in the configured group supports
that model. The same provider's live `/models` response also omitted Luna.
No automatic substitution or repeated model calls followed this confirmed
failure. A supported Luna channel or an explicit replacement choice is needed
before answer comparison can continue. The actual calibration failure is
visible under the original-run record. No frozen answer experiment, candidate
answer gain, or new Knowledge-connected App delivery is claimed.

## 用户从前端如何重复操作

1. 在资料来源网站下载文件。打开项目的「知识库实验 → 资料」，上传语料
   JSONL；如果资料已经位于执行器上，也可以填写文件夹绝对路径。这里的
   路径属于执行器，远程 SaaS 用户本机的路径不能直接当作服务器路径。
2. 检查导入数量和原文预览。来源字段不同可展开字段映射；问题与答案文件
   应在评测页单独导入，不能混进回答者使用的知识语料。
3. 在「索引与检索」选择切片方式、长度和重叠并建立新索引。旧版本保留。
   没有真实 Embedding 配置时先跑关键词基线；配置语义服务后需要建立新的
   语义索引，不能把原关键词索引改名冒充向量索引。
4. 有评测集：导入 JSONL/CSV，核对来源关联和派生分组。没有评测集：选择
   建立待审核标准，模型起草的题目保持合成来源标记，逐题审核后才使用。
5. 先在开发集比较检索配置，选定后检查保留集。前端保留每次索引、分组、
   分母和实际指标，重复使用保留集会记录次数。
6. 进入回答评测时明确题数预算；完整知识库仍参与每题检索。核对标准，
   标注样例并记录审核来源，校准当前评审模型，冻结后再跑基线与候选。
   当前演示因用户指定的 Luna 通道不可用而停在重新校准处。


## Next implementation: Knowledge-backed application delivery

The model-channel failure blocks live answer comparison, but application
packaging can progress independently. The following bounded work preserves the
full-index requirement through the existing generic App owner:

1. Add a read-only search snapshot contract to KnowledgeStore and its owned
   RagBenchmarkSandbox API. Export only explicit base/document/chunk fields,
   never the machine database, filesystem paths, credentials or evaluation
   references. Rehydrate a package-local cache through the same KnowledgeStore.
2. Freeze an optional scoped Knowledge binding with an App source version.
   PAW and standalone packages use the same frozen source/chunk snapshot and
   KnowledgeStore lexical implementation. Validate ranking parity against the
   selected Lab index. The first portable contract supports the current lexical,
   no-reranker profile and explicitly rejects unsupported semantic profiles.
3. Extend App actions with an explicit retrieval-only operation for inspectable
   source results without a model call; answer actions still use their frozen
   model and bounded retrieved evidence. Preserve invocation idempotency and
   immutable existing package versions.
4. Show the Knowledge dependency in delivery and expose preparation from an
   existing project source directory through the existing prepare_app command.
   Verify preparation, real retrieval and export through the frontend. Live
   answer quality still requires the user-specified Luna channel.

Acceptance is actual frozen-package retrieval parity, bounded solver evidence,
no reference-label leakage, persistent operation receipts and visible exported
runtime requirements. A retrieval-only success is not an answer-quality result.


### 2026-09-07：按用户截图恢复 OpenAI Codex Luna 通道

用户截图明确选中 `openai-codex / GPT-5.6 Luna / 最高`。此前候选实例使用 `gpt` 网关，且隔离 Pi auth.json 为空；该网关的 404 不能证明截图中的通道不可用。实读现有 PAW 8768 模型目录确认 openai-codex 登录与 Luna 七档推理。复用 `scripts/pi_canary_support.py::stage_openai_codex_oauth` 将现有登录放入仓库外、权限 0600 的候选 Pi 配置；原实例未改动，凭据不进入 App、源代码、日志或报告。候选进程改为 33531，端口仍为 18868。

前端改选正确服务并保存为标准 v10。三条调用完成，但首次校准为 2/3：错误答案的 Judge 实际返回 fail，引用添加了原文没有的换行，严格证据校验将其降为 uncertain。没有改标签或放松校验。在前端补充短段连续逐字引用说明，保存为 v11，再校准得到 3/3、无误通过/误拒绝/不确定。标签来源仍为 Agent 3、人类 0，仅用于流程验证。

前端冻结快照 `golden-snapshot:caed70c4-a3ce-48b8-abcc-1508273b2fce`，确认基线、候选、评审全部 `openai-codex / gpt-5.6-luna / max`，启动 1 开发题、3 留出题、最多 1 次 Prompt 候选的实验 `golden-job:5000cc0f-e3ce-4bcc-832e-dda98af8bb59`。截至本条记录写入，实验仍在执行；不预写效果结论。

### 知识库应用交付实现与验证

应用使用 PAW 既有白色阅读面和绿色操作色，扩展问答加来源双栏；窄屏顺序为问题、回答、来源。主操作为生成回答，辅助操作先查来源和恢复最近记录。加载、失败保留输入，显示真实来源，不预置答案。

大型知识资源落在版本拥有的不可变 `lab-app-packages` 目录，SQLite 仅保存文件清单与摘要；轮询应用版本不会反复返回知识库正文或 ZIP。导出时才按需读取已冻结 ZIP。两个导出目标使用同一份 KnowledgeStore、models、permissions 源组件及独立检索适配器，包内恢复专属 FTS5 缓存。当前支持 lexical/no-rerank；不能默默将 dense/hybrid/rerank 降为关键词包。

新增集成测试验证真实 20 文档索引：PAW 与独立 HTTP 服务返回的来源、切片、文本完全一致；重复请求不重复执行；来源查询 0 模型调用；回答仅获得 bounded retrieved sources，未包含原始参考答案；快照损坏在 Provider 调用前明确失败；数据库版本行不含资源正文或 base64。该单测通过，新增功能尚待真实 Wix App 前端验收。


### 实跑恢复补齐：已取消的 Pi 回合

12:21 候选进程 33531 意外退出，18868 无监听，日志没有 Python 异常栈，退出原因未确认。重启后前端如实显示连接恢复及实验 interrupted。点击“恢复任务”读取原 Pi 结算，未完成回合确认为 cancelled，13 次成功调用已保留。发现 `_retryable_request` 仅接受 failed，导致这种已确认未成功结束的回合没有继续入口。

新增用例先重现 cancelled/aborted 均不显示恢复，再将资格限制扩展为同一个 pendingRequestId、完整 sessionId/turnId、明确 failed/cancelled/aborted 结算。accepted/interrupted/unknown 仍不能创建新尝试；完成调用继续按原身份复用。`resume` 由前端显式触发，新尝试追加 `:retry:1` 和 retryHistory，历史回执不改写。55 个 Golden/执行测试通过；另加同身份 unknown/accepted/interrupted 用例通过。候选随后在所有 Lab 任务空闲时更新为进程 38832，前端点击“重试未完成部分”继续同一个实验。

应用/知识库/项目有效测试共 46 项通过；一次组合命令误写了不存在的 test_agent_lab_project_application 模块，产生一个收集错误，实际测试无失败。随后正确的 App runtime、项目 routes、history 19 项通过。应用和项目工作台前端 23 项通过，TypeScript 检查通过，Vite 构建完成（11.76 秒），harness/import boundaries/route ownership/diff 检查通过。Impeccable 检测器退化为 regex，返回 0 条；不据此声称已验证计算样式或对比度。

## 追加原始需求：App 生成提示词与模板（2026-09-07 12:48–12:58）

- 用户原话（04:48:39.674708Z，message 806972595）：**“app导出要多给反馈，比如召回哪些，思考中这些，这是交互的基本逻辑”**。
- 用户澄清（04:58:39.075576Z，message 294222919）：**“就是做app的提示词或者模板要优化”**。
- 需求含义：优化可复用的 App 制作入口与模板，让以后生成的 App 默认具备基本过程反馈；当前 Wix App 是验证实例。不能把只修改一个实例页面当作完成。

对应源入口：`agent-lab-project/SKILL.md`、`references/apps.md`、新增 `assets/portable-app.html`，以及项目 `commandGuide.prepare_app.interaction`。原生 Extension App 的 `pawos-app-builder/references/frontend-contract.md` 同步要求共享 Session 中的真实过程展示，继续复用 Pi/Session UI。

交互约定：提交即确认并防重复；真实检索完成即展示采用来源及未采用候选；来源展开状态不随回答流重置；等待/思考/输出来自 Runtime 公开事件，不编造阶段或百分比；输出尚未完成时明确标记；错误保留输入/来源；历史恢复不重放模型调用、不保留旧错误样式、不覆盖进行中的回答。

支持基础：append-only migration 0197 保存独立的 App progress；Pi adapter 只读取精确 Session/turn 的公开事件，最终结果仍由 settlement receipt 决定；PAW iframe 和独立包均支持第三参数 `onProgress`；独立服务支持 OpenAI-compatible SSE，未收到结束标志的中断输出保持未确认。原有两参数调用兼容。知识数据、方法、模型与评测质量结论不因 UI 反馈改变。

源码检查：后端 App/独立服务/Pi/Knowledge 共 58 tests 通过；新增模板 DOM 与 bridge 行为后前端 12 tests 通过；TypeScript 通过；harness/import boundaries/route ownership/diff 通过。额外按不存在的测试名选取导致的两次 collection error 已纠正；修正后真实 Knowledge App 集成单测通过。前台及导出包反馈验收另附实测结果，不以这些检查代替。

### 13:30 收口：可复用交互规范与 App v4

- 生成入口及可复用 HTML 已同步，项目实时 `commandGuide.prepare_app.interaction` 已读回确认。原生 App Builder 规范同步要求沿用共享 Session 过程展示。本次未修改已安装原生 PAW 或原生 managed Pi 的 Skill 包。
- 前台从 `wix-knowledge-app` 准备并启用 v4；contentHash `3e3b7f58102c49a887b4f8eac1f80a2ed1b3e52f5a761775a9762c7a2d38f311`。模型仍为 `openai-codex/gpt-5.6-luna/max`，知识快照、检索参数、基线方法保持原值。
- 两条真实 v4 回答均 completed。其中 `lab-app-call-398320d2025b4a4ba817350482522b53` 完整记录 retrieving → sources_ready → model_starting → model_wait → thinking → answering → completed；第一次回答实际结算约 13.0 秒。第二次在前台真实观察到“模型正在思考”同时展示来源，随后“回答生成中 · 尚未完成”显示仅输出到 `3. Right` 的部分正文；展开的来源在最终完成后仍打开。这是过程交互验收，不是新的无偏质量实验。
- PAW 与独立包使用同一输入时，20 个召回候选、16 段采用原文逐项相同；两种包的 HTML、Skill、App 配置、运行器及知识文件逐字节相同。
- 当前 IAB 里点击 v4 下载发出了正确请求并获得 HTTP 200，但浏览器的 `Page.downloadProgress` 为 `canceled`、receivedBytes=0；支持的 download 等待接口也未交付文件。因而 v4 **不记为浏览器下载验收通过**。同一不可变导出 GET 的两个 ZIP 已由操作者保存，校验大小、SHA-256、ZIP CRC 和成员路径后解压运行；v3 较早的真实浏览器下载证据独立保留。
- v4 独立包真实前台完成本地检索；缺少目标模型配置时明确报错并保留原问题和全部来源。历史恢复清除错误样式，记录数仍为 2（一次成功检索、一次配置失败），没有新增模型调用。没有独立包真实 Provider 回答的验收声明；SSE 输出与中断通过受控解析、HTTP 存储及模板测试验证。
- 有效截图位于 `.impeccable/review/lab-app-feedback-20260907/`：`paw-thinking.jpg`、`paw-completed.jpg`、`standalone-error.jpg`、`standalone-mobile-retina.png`。最后一张为 390×844 CSS 视口、780×1688 Retina 图；浏览器视口已恢复默认。没有把最终截图冒充流式阶段截图。
- 新鲜、只读的界面审阅结果为 **Ship**，没有 material findings；另复查 12 项前端、45 项相关后端、TypeScript 与 diff。审阅没有证明实际独立 Provider、原生安装或计算对比度。
- `python3 scripts/check_public_release.py --repository-only` **未通过**：已有 `.impeccable/review/painterly-20260906/assets.json:46` 含机器路径，且工作区存在未提交修改。未修改该不相关材料，也未提交、推送、构建原生发行包或发布。harness、import boundaries、route ownership、TypeScript、聚焦回归及 diff 检查结果与此发布检查分开记录。

候选外部证据目录保留 `acceptance/knowledge-feedback-final.json`（实际调用、来源对齐、独立记录）、`acceptance/knowledge-feedback-exports.json`（同一冻结版本的导出文件与下载限制）、`acceptance/app-builder-interaction-contract.json`（实时生成规范）。这三份归档不进入 App 提示词或知识索引。独立包实际文件为 `lab-app-v4-standalone.zip`（7,012,340 bytes，SHA-256 `8276f81baaa2d27760891185ecc1c69d5a9c3d755b3a66712c1d11120b3528f7`）与 `lab-app-v4-paw.zip`（7,012,737 bytes，SHA-256 `295036e0a4f9cb807646bf68faf2855a02d7196302d514b592dda76554e2af56`）。

Golden 的正式比较仍为 inconclusive，保留基线方法；没有因为交互改进重跑留出题、改标签或宣称回答质量得到提升。
