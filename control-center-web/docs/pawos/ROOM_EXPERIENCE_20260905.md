# Room experience progress — 2026-09-05

> Subsequent user review rejected the large Home chooser and five-panel Room
> focus layout. The earlier independent review below is historical, not user
> acceptance of the current layout. Whole-OS redesign remains active (UR-253).

## Accepted direction and implemented source

User corrections: “深色不好，还是白色吧，app少有见到深色设计”；“你要有审美把控”。
The current design uses white reading surfaces, quiet gray process sections,
and restrained blue actions. Planets identify partners; satellites identify
their actual Session Tool Agents. This replaces the earlier dark treatment.

- Agent home, desktop labels, Room result reading, code highlighting, and
  narrow-window layouts share the light visual language.
- Room has a dedicated message-flow view with sender, receiver, delivery state,
  full message body, and navigation to the message being replied to. Partner
  satellite counts come from Session data, deduplicate retries, and distinguish
  loading/error from a confirmed empty list. Historical settled traffic does
  not animate as running.
- Main results retain the full moderator report; collaboration process and
  partner details expand separately. A stopped round retains its output.
- Root cancellation replay settles frontend state. Session snapshot recovery
  retains confirmed history and a newly admitted local prompt without reviving
  old activity. Unhydrated Room rows describe tasks/deliveries rather than
  claiming that Pi is running or completed.
- Backend recovery includes dispatches whose WorkResult arrived before their
  Pi terminal event. Stable pagination avoids starvation; live and recovery
  terminal publishing share an idempotent owner.
- New Room controls show effective Room, Partner, and Tool Agent permissions.
  Default full-trust inheritance is visible; explicit restrictions remain
  effective, including nested child delegation.

## Verification and limits

Source browser at `http://127.0.0.1:5183/#/agent` used the existing local HTTP
Gateway. No demonstration events or model messages were inserted. In a real
retained Room, the header showed “本轮已停止”, Stop was absent, and the full
report remained readable. Its planets showed Earth 0, Mars 0, Venus 2, with
Venus split into returned 1 and timed out 1. Another real Room supplied a
Mars-to-Earth reply with navigation to its Earth-to-Mars question.

White home, results, code, and message-flow screenshots are local review
artifacts under `.impeccable/review/white-*.png`. Wide and actual 624px app-window
layouts were inspected. Independent Astra review found no required visual
rework; its narrow stopped-state ambiguity was addressed with a short label
and neutral state dot.

Checks passed in their bounded scope:

- Integrated frontend suite: 11 files, 298 tests, covering reducers, live store,
  Agent/Room workspaces, results, satellite host, and syntax highlighting.
- Message-flow/projection suite: 6 files, 83 tests; theme suite: 43 tests.
- Backend terminal/recovery suite: 76 tests, including cross-owner deduplication
  and pagination beyond 500 settled dispatches.
- TypeScript project check and production HTTP Vite build. Existing large
  chunk warnings remain. Import/route boundaries and project harness passed.

These checks overlap and must not be added together as unique test counts.
The installed app remains build 1427; no installation or release was performed.
Source browser acceptance does not prove installed backend recovery. A retained
historical orphan with no exact Pi terminal evidence remains an open recovery
case; it must not be guessed completed from an idle snapshot.

## Remaining work

Validate the candidate through the installed product, including refresh,
reconnection, cancellation and long-window restoration. Then finish Agent Lab
as the accepted experiment-centered Enterprise RAG workflow: two-layer
optimization, actual patch diff, exact baseline Trace, per-case comparison,
and real Room candidate validation. This UI work does not close Lab or all
250 indexed requirements. No commit or push was performed for these changes.

## Subsequent redesign and reproduced failure

The Home now uses the same ModelPicker as the live Session composer. Its
compact default exposes reasoning, with model search disclosed on demand in a
viewport-aware portal. The obsolete Home model menu, greeting and decorative
geometry were removed. The Home title/instructions were shortened; active Room
records no longer imply that a turn is running. Source UI checks covered a
1280px maximized surface and a real 750px restored window; the 300px chooser
remained inside the viewport, with no horizontal composer overflow.

The combined Home/ModelPicker/Lab contract/Desktop tests passed 91 checks.
Lab dispatch now validates its final scenario including domain context against
Room's 8000-character persistence limit, preventing silent JSON truncation.
Tool timeline source passed 97 focused checks for terminal motion, per-Session
disclosure persistence, growth without collapse, and background pause.

The reported Room send failure was located in a real failed command receipt:
2026-09-05 08:31:46–08:31:54, error `Agent 3 is currently busy`; no new Room
user-message or Root was created. It is distinct from the old plugin validation
error quoted in the previous result. The active repair investigates prewarming
holding the direct-user priority claim. The new Room focus layout and Memory
redesign are still being implemented. No fresh send acceptance or installation
is claimed by this entry.

## Installed candidate 1428 and real Room acceptance

On 2026-09-05 the supported stack installer completed from the isolated
`20260905-091347-white-agent-lab` source snapshot. The installed Electron App
and HTTP frontend are build 1428, source `046b87e8a284a7775267dda601ef18e93f5d8fc5`
with explicitly recorded uncommitted changes. Gateway and Sidecar health passed;
Pi activated `pi-0.84.2-9c3f93c8b1c4-raghost-74b325f474`. The immediately previous
generation and a separate pre-install App/configuration recovery copy remain.
No commit, push, public release, or user-database replacement was performed.

The full frontend run covered 263 files / 2939 tests. Its 16 failures were old
Home/ModelPicker interaction assertions in two files; both complete files were
then rerun with the new interaction and passed 177/177. The other 261 files had
already passed. Production build/typecheck passed. The frozen backend smoke
passed 55 tests with one private-input test skipped; the Memory month-range
change separately passed 101 relevant tests.

The original draft `是什么问题呀` was submitted through the installed HTTP UI
to Room `room:1e7e336e-753b-4d1c-a995-9901131f3ee6`. Receipt
`paw-room-b0955083-d2a2-4a5e-a21b-414c816e2340` was accepted without the earlier
busy error. Root `room-turn:3967f5bc-9ce5-4e55-bf0f-fed9910aa5ad` contains one
user message (sequence 814) and one `turn_completed` (sequence 963). The UI
showed the real response, Room completed, a completed Earth, and an empty
composer. Browser reload preserved completed/synchronized state and did not
create another message or terminal. The desktop App also opened build 1428's
new Agent Home and the retained Room; a subsequent desktop-window interruption
prevented completing the native Room interaction check, so the complete send /
reload receipt belongs to the installed HTTP UI.

Historical child `room-child:96462b27-43c1-5feb-8df6-02292e245e55` gained exactly
one missing public terminal, sequence 3847, from Pi event
`agent:0255767f-f4fa-4eb6-ab72-d2fa7b82ce42:917`. Two further snapshots kept that
count at one and preserved its existing dispatch/result metadata. Its Root's
two older terminal records both predate this installation; no new Root terminal
was added by this repair. Local machine receipts are
`/tmp/paw-room-installed-send.json`, `/tmp/paw-room-installed-recovery.json`,
`/tmp/paw-candidate-install-input.json`, and `/tmp/paw-candidate-install.log`.

## Follow-up work outside candidate 1428

- The live reply exposed idle roster cards reappearing while the moderator's
  streamed reply replaced its task lane. Source now excludes those idle cards
  and counts the actual coordinator lane; the regression reproduced first,
  then both related suites passed 34/34. This change is not yet installed.
- Knowledge search/reading/return state has been redesigned in source, with
  62 tests passing. Real source UI verification and installation remain.
- Memory's hourly job failed with a settlement-read timeout and a cold Session
  recovery error. Source recovery now reopens the original Session and reads
  its exact durable turn without another prompt; 160 focused tests passed.
  Historical settlement availability is unverified, and this repair is not
  installed. Do not claim that the historical job has recovered.
- A real Room diagnosis led to an independently confirmed plugins Tool schema
  mismatch and overly broad unavailable-error mapping. The next source patch
  is under implementation, not an installed plugin or successful plugin run.
- Lab still needs an actual scene-version application/rollback owner and real
  new candidate execution. Other App workflows and native long-run acceptance
  remain open; candidate 1428 is not whole-system completion.

## Recovery candidate and additional real interaction findings

The next isolated snapshot is `20260905-102045-recovery-knowledge`, copied from
the verified 1428 snapshot plus explicitly ready files. It excludes the new
Lab scene recipe owner, routes and runner while their integration is active.
The verified 1428 App, installed code, Skills/prompts, LaunchAgents and Pi
pointer have a separate recovery copy at
`install-recovery/20260905-102338-before-recovery-update`; no databases or
Session history were copied or replaced.

- Frozen recovery checks passed 72 backend tests and 224 frontend tests in
  16 files. Production build/typecheck passed; import and route boundaries
  passed. The root Outcome wording was shortened to restore its context budget.
- Memory's five recovery files passed independent review. An original accepted
  turn is reopened without a new prompt; a lookup timeout remains resumable.
  This is source/fixture evidence, not recovery of the historical hourly job.
- Plugins now expose Package sources and metadata, preserve the Host-created
  draft source for subsequent native validation, and distinguish business
  rejection, internal failure and temporary unavailability. The unknown-result
  path does not automatically replay the operation. The independent reviewer
  closed both discovered defects after five focused checks.
- A real Knowledge query `强化学习` returned ten results. Selecting DeepSeekMath
  page 18, opening its source and returning preserved the query, result list and
  exact selected hit. The 750px reader now keeps status/statistics on a separate
  line, highlights the matched paragraph in blue and folds assembly history.
  The delete action is in More; keyboard selection opened its confirmation,
  and Cancel preserved the library and restored focus to More.
- Real mouse selection of that menu exposed a shared desktop defect: React
  Portal pointer events reached the desktop lasso, which captured the pointer.
  Its fix and real mouse recheck are required before installing this candidate.
- Direct navigation from a focused Room to Lab now exits only the collaboration
  layout, retaining the Room. Two regressions failed before the fix; 72 related
  store/route tests passed. The actual source browser showed Lab in front and
  no leftover focus overlay.
- RAG r6 public scores were internally consistent; the frontend combined two
  different denominators. It now shows tasks 3/4→4/4, answerable answers 1/2→2/2,
  citation facts 7/9→9/9 and abstentions 2/2→2/2. API cost is a Runtime-reconciled
  estimate for all four lanes plus the frozen Judge, $2.170603→$0.1029376, not a
  Provider bill. Source UI matched these results. No scorer or ledger changed.

The Lab scene-version work is a separate integration: immutable configuration
versions, application/rollback records and a frozen binding for each future
Validation run. It must reach the actual runner and UI before being called
complete; recording a selection alone does not prove an experiment used it.

### Desktop menu pointer acceptance — 2026-09-05 10:40 CST

- Source UI at 5183: a real mouse click on Knowledge More > Delete now opens the confirmation dialog. Cancel closes it, restores focus to More, and preserves the selected knowledge base with 4 files / 447 chunks and the 10-result search. No delete was submitted.
- Root cause: body Portal pointerdown bubbled through the desktop React tree and began lasso pointer capture. The desktop now checks DOM containment and excludes interactive roles. Five regressions cover Portal and inline interactions; normal background lasso remains covered.
- This source acceptance precedes installation of the frozen recovery candidate; native and installed acceptance are separate.

### Installed recovery update — 2026-09-05 10:46 CST

- Supported stack installation from `20260905-102045-recovery-knowledge` completed with `--skip-pi`, reusing the verified Pi generation. The initial include-Pi attempt stopped before activation because the same version was rebuilt under a different source path; comparison confirmed that the only provider-bridge difference was the snapshot path. No existing generation was overwritten. Logs: `/tmp/paw-recovery-candidate-install.log` (failed packaging attempt), `/tmp/paw-recovery-candidate-install-reuse-pi.log` (successful installation).
- The installer retained build number 1428; the new App marker timestamp is `2026-09-05T02:45:39.225336+00:00`. This is a new local installation from the recovery snapshot, not build 1429. Gateway Runtime ready/active arrays empty and Sidecar health passed.
- Installed HTTP UI reload shows Lab task success 3/4 to 4/4, answerable correctness 1/2 to 2/2, cited facts 7/9 to 9/9, and scoped API estimates $2.1706 to $0.1029. The retained failed-draft Room reload remains completed/synchronized; coordinator-only rounds show one participating planet and no invented idle collaboration rows.
- Desktop/Knowledge frozen final suite passed 89/89 after Portal correction and production build passed. New Lab scene owner/runner/application remain outside this installed snapshot. The historical Memory job has not been declared recovered.

### Lab result reading and browser start — 2026-09-05 11:08 CST

- The result page now presents task success, cited-fact coverage and scoped API estimate as three typed before/after measurements. Complete quality/reliability/cost wording remains under one disclosure. The owner preserves separate answerable/abstention populations; missing numeric evidence is never replaced with zero.
- Removed the obsolete result overview component markup/CSS and moved archive navigation into the existing toolbar, leaving the current experiment and its four steps primary. Actual 1035-by-492 and 751-by-492 windows were reviewed; primary figures fit the wide first fold, the narrow layout stacks, and the app/result content has no horizontal overflow. Screenshots: `.impeccable/review/lab-result-summary-1035.png` and `lab-result-summary-750.png`.
- A real HTTP connection has no native file picker. The prior picker-only Lab setup could never start from a browser. It now accepts a candidate directory path on those connections; native connections keep their picker. The failing start test was reproduced then passed, and the real source browser exposes the field. Existing path/contract validation stays in effect.
- An isolated local acceptance workspace with verified input references is prepared at `<PAW_STORAGE>/lab-candidates/20260905-scene-recipe-acceptance`. No new Provider run or live scene apply/rollback has occurred yet.

### Continued Session — 2026-09-05 evening

The continuing task is `01a070e8-ba60-7390-a628-8bef2d3c2e1b`. Direct user
messages below are requirements; attached screenshots and ambient browser
state remain supporting evidence, not separate instructions.

| Source message / UTC | User wording | Interpretation / current boundary |
| --- | --- | --- |
| `msg_01a07103-be44-7a83-9aa9-4fadc2b609a8`, 10:01:05 | “全部，整个os的ui都需要优化，我们讨论一下如何加动效，比如现在背景简单，完全可以加一个伪3d的星际，好看的那种” | Whole OS visual and motion discussion continues UR-253; not only wallpaper. |
| `msg_01a0710c-56f3-7953-b3d3-b98aad4e909b`, 10:10:29 | “浅色宇宙，通透有纵深（推荐）” | Explicit answer selects light stellar depth with white App reading surfaces. |
| `msg_01a0710c-56f7-7a31-8720-61f79235c212`, 10:10:29 | “登录还没解决，我得登录来继续完成面试的那些数值” | OAuth repair first; resume actual metrics only after credential acceptance. |
| `msg_01a07117-b110-7f80-9c61-3c62c777a42d`, 10:22:53 | “协同模式行星没有弹出窗口” | Diagnose real planet-to-window behavior. |
| `msg_01a07118-d253-7163-bd42-37e0b681e68c`, 10:24:07 | “需要运行的行星都弹出” | Open every partner participating in current execution, including later entrants. |
| `msg_01a07118-d25e-7583-bfca-c1da2159cf31`, 10:24:07 | “一个窗口不够” | Replace the single selected-partner visibility restriction; preserve simultaneous independent windows. |
| `msg_01a0711e-6f1e-7a22-9554-3a7d25dd10b0`, 10:30:15 | “前后端同步问题需要优化。Runtime 未及时返回轨迹快照；对话不受影响。请稍后重新读取。**重新读取**” | Trace recovery and Session first paint require actual build-1428 verification, not source-only acceptance. |

Fresh evidence before the remaining fixes:

- In source HTTP UI `127.0.0.1:5183`, the four-partner retained Room creates
  four `agent:participant:*` shells but marks all hidden on entering cooperation.
  Clicking Earth makes it visible; clicking Mars then hides Earth. This is a
  reproduced single-selection layout limitation, not failure to create a window.
- Desktop icon single-click selects; Dock click opens. That existing distinction
  was verified and is not included as a bug.
- All four retained partners must not be labeled running: Earth is completed;
  Mars/Venus/Jupiter are idle. Auto-open tests must use actual active-participant
  projections rather than resurrect old Room state.
- Runtime `messages?view=recent` returned five retained messages in about 0.318s,
  while `debug-context` returned `runtime_unresponsive` in about 1.13s. This
  localizes a trace path discrepancy; further diagnosis and installed acceptance
  remain pending at this receipt.

OAuth repair is separately complete at the live authentication boundary:

- The bundled login interaction lacked the AbortSignal required by Pi 0.84.2.
  Browser login bound port 1455 before throwing; device login also threw.
  Source bridge/lifecycle/HTTP regression checks passed 14 tests.
- Standard builder and deterministic staged Session acceptance produced and
  activated `pi-0.84.2-9c3f93c8b1c4-raghost-b33df9afea`. It retains the same Pi
  source revision, explicit dependency-symlink dirty digest and Runtime contract
  as the prior `74b325f474` generation; the prior generation remains available.
- After verifying no active Session/completion, the proven failed login orphan
  PID 52905 was terminated and Gateway restarted. Browser OAuth completed at
  18:13 CST. The refreshed PAW-managed credential then returned `OK` from a real
  Luna/low completion in 2.659s, 26 tokens. This diagnostic is excluded from all
  interview metrics.
- Build/install/acceptance receipts and previous pointer are under
  `<PAW_STORAGE>/install-candidates/`, named
  `pi-oauth-signal-20260905*`. No credentials were printed or committed. The
  Python auth-process cleanup source fix still awaits the complete backend
  application installation; only the corrected bundled OAuth bridge is installed
  by this Runtime generation receipt.


### Causal continuation record — 2026-09-05 evening

[The unified reliability record](PAWOS_RELIABILITY_CONTINUATION_20260905.md)
connects UR-260–UR-264 to the OAuth lifecycle failure, 47.24 MB trace transport,
independent partner-window visibility, accepted-turn recovery, and the Pi dirty
source/version collision. The earlier 0.318/1.13-second probes above are
pre-fix observations. Source tests, staged generation, activation, and native
verification remain separate in that record; it owns the final installation
receipt and outstanding boundaries.
