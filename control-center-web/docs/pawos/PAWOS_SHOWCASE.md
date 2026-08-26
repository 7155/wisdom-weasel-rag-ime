# PAWOS Showcase And Final Verification

This is the owned closeout record for the 2026-08-27 final showcase Goal. It
does not replace Runtime, Git, installation, or foreground evidence.

## Source request

Source ref: `TaskBrief.user_message.current`

> 根据他的任务，接续，包括调用子agent，来完成前端，各种功能，数据整理，文档整理，后端检查。设置goal。对项目最后检查和功能核验，最最后**读当前仓库 → 自己找出最值得展示的能力 → 自己设计 Demo 剧本 → 自己把录制链路搭出来**。来补充readme宣传和截图，这种的环境和技能你可以直接安装。

## Requirement mapping

| ID | Meaning | Acceptance owner |
| --- | --- | --- |
| `UR-150` | Select the showcase capability from current source and fresh evidence. | Main Agent |
| `UR-151` | Make the Demo, screenshots, recording, retry, and cleanup reproducible. | Main Agent |
| `UR-152` | Keep README claims and media inside explicit evidence boundaries. | Main Agent |
| `CLOSE-001` | Coordinate bounded frontend, docs/data, and backend audits; finish proportional verification. | Main Agent and named audit Agents |
| `CLOSE-002` | The user authorizes installing only the environments or Skills needed for this closeout. | Main Agent |

## Current execution record

- Goal: `01a03ea7-1007-7e30-837a-b8c88875a374`
- Workspace: isolated Goal worktree; unrelated dirty worktrees remain untouched.
- Environment: the lockfile-defined frontend dependencies were installed in
  this worktree. Existing Node, pnpm, Playwright, ffmpeg, cwebp, and macOS
  screenshot tooling were reused; no additional Skill package was installed.
- Evidence rule: public deterministic fixture capture, live Web Runtime,
  installed native foreground, and release readiness are separate verdicts.

## Showcase decision

| Candidate | Decision | Evidence and reason | Boundary kept open |
| --- | --- | --- | --- |
| Agent Session | **Lead scene** | The current PAWOS source and public fixture show one resumable Session, Tool chronology, context assembly, token composition, and evidence navigation without replacing the final answer with internal logs. | The published image is E2 preview evidence, not a personal live Session or native foreground receipt. |
| Multi-Agent Room | **Lead scene** | Current Room reducers, Partner workflow tests, satellite windows, and the same collaboration state rendered as focus overview or starfield express PAW's product center: ordinary accountable Partner Sessions with one Root result. | The published scenes are deterministic fixtures. The installed Pi payload was exercised separately and is not represented by these pixels. |
| Governed Memory and Knowledge | Supporting evidence inside the Agent scene | Context assembly is more legible as part of the Session story than as another dashboard screenshot. The Memory graph also gained a bounded recovery path in this closeout. | No claim that the screenshot contains the user's live Memory or Knowledge data. |
| Browser, IME, voice, desktop semantics | Not promoted to the lead | They remain important optional adapters, but this run did not obtain a fresh unlocked macOS foreground receipt. Installed Squirrel, Pi, and MLX generations also remain older than this product revision. | Source, build, service health, or historical acceptance cannot replace current E6. |

The selected story is therefore **inspectable Agent Session → accountable
multi-Agent Room**. It demonstrates the product center and can be reproduced
without personal data. Browser, IME, and voice stay in the capability table and
release warnings rather than being upgraded by an attractive screenshot.

## Reproducible Demo

### Preconditions

- Node 22, pnpm 11, Playwright Chromium, and `cwebp` are available.
- `control-center-web` dependencies match `pnpm-lock.yaml`.
- Port `4177` is free. The dedicated Playwright web server is started and
  stopped by the capture run.

From the repository root:

```bash
scripts/capture_pawos_showcase.sh
```

The command is safe to rerun after interruption. It clears only the capture
page's local storage, rewrites the three owned files in `assets/showcase/`, and
replaces the ignored recording under `control-center-web/output/showcase/`.
It does not open, modify, or record personal Sessions, Rooms, Memory, databases,
browser profiles, credentials, or input history.

### Scripted scene

1. Open the public `session-preview` in PAWOS and wait for the synchronized
   Session workspace.
2. Open **Agent 轨迹**, switch to **上下文装配**, verify the token-composition
   visualization, and capture `pawos-agent-trace.webp`.
3. Navigate to public `room-preview`, verify the synchronized Room and its
   named WorkItem, then open **协作态势**.
4. Detach the Sol overview into its satellite window and capture
   `pawos-room-focus-satellite.webp`.
5. Switch the same Room to **星空**, force the deterministic 2D renderer, and
   enable reduced motion before capturing `pawos-room-starfield.webp`.
6. Save the full 1440×900 tour as the ignored `pawos-showcase.webm`, then write
   asset hashes, the base commit, working-tree fingerprint, data source, and
   evidence boundary to `assets/showcase/showcase-manifest.json`.

The final run passed `1/1` Playwright capture test. The WebM is VP8, 1440×900,
25 fps, approximately 12 seconds. A contact-sheet review confirmed the
sequence Agent → trace → Room → satellite → starfield and found no personal
data. The three tracked WebP files are the only images published in README.
The fixed browser clock, named checkpoints, and reduced-motion starfield make
the semantic tour reproducible. Manifest hashes identify the current run; they
are not cross-machine golden-image claims because Chromium/GPU rasterization
can introduce small pixel-level differences in gradients and window shadows.

## Verification ledger

| Boundary | Status | Evidence |
| --- | --- | --- |
| E1 Source | **passed for this closeout** | Agent/Room routing, PAWOS and legacy active-turn mention semantics, an adaptive horizontal Focus rail that preserves 5/8-participant windows at 800×720, eight distinct participant windows, Memory graph recovery, legacy mobile layout, shared disclosure exit behavior, capture configuration, manifest writer, README, and UR-150–UR-152 are present in the isolated Goal worktree based on `50834992fb8489b6709c8212d066693f6572eab0`. Unrelated dirty worktrees were not reset, stashed, cleaned, or merged. |
| E2 Test | **passed with an explicit broad-Python rerun boundary** | The final frontend suite passed 2,184/2,184 tests across 214 files; focused Room regressions passed for plain active steer, single explicit mention, multiple-mention draft retention, PAWOS parity, and 800×720 Focus layout. PAWOS product scenes passed 15/15 at desktop, tablet, and mobile; Electron host tests passed 14/14; showcase capture passed 1/1 in both the Goal worktree and a disposable clean checkout with only the lockfile dependencies and Playwright Chromium installed. The Python suite first ran 3,520 tests with one stale 149→152 ledger assertion and three skips; the assertion was corrected and its six-test module passed, but all 3,520 were not repeated. Project harness, import boundaries, route ownership, requirement checker, TypeScript typecheck, and `git diff --check` pass. Repeated Python 3.14 unclosed-SQLite `ResourceWarning`s remain a backend quality issue. |
| E3 Build | **passed as a dirty development build** | Preview/auto, production/native, and production/http Web builds each passed their transport/channel boundary checker. `build/RagImeControlElectron.app` was built at 301 MB and passed `codesign --verify --deep --strict`; its marker identifies the base commit, `release`, `production/http`, excluded preview fixtures, and `gitDirty=true`. Chunk-size warnings remain non-fatal. |
| E4 Install | **passed for the named development components** | The official stack installer completed with `RAG_IME_ALLOW_DIRTY_INSTALL=1 --skip-pi --skip-mlx`, then the release Electron host was installed with the same source marker and a same-revision WebKit fallback. Control, Desktop Bridge, Voice, Sidecar, Memory maintenance, and Pi Skills are current to the base commit but intentionally fail clean-release provenance because the source is dirty. Pi Runtime, MLX, and Squirrel were retained and remain older/mismatched. |
| E5 Runtime | **partially passed** | Loopback Sidecar/Gateway listeners are live on 8766/8768; Sidecar health is `ok`, local predictor is configured, and Memory projection is running. The retained installed Pi payload passed isolated deterministic `session.open/prompt/steer/debug/abort/snapshot` and Room Partner/WorkItem/review/Stop/unique-final smokes. Those receipts report `productionEnabled=false` and the Pi payload's older product generation, so they do not prove a current production Room. |
| E6 Foreground | **blocked** | `computer-use` reached the exact installed app path but macOS was locked and automatic unlock was unavailable. No foreground interaction or screenshot was claimed. |
| Release | **blocked** | `check_public_release.py --repository-only` truthfully fails on forbidden tracked handoff artifacts, machine-specific paths, the dirty worktree, pending foreground acceptance, declared blocked product status, and a missing release manifest. Ad-hoc signing is build integrity, not Developer ID signing, notarization, or stapling. |

The Impeccable detector was also run over every changed UI owner. Its findings
were legacy side-accent/bounce patterns outside the changed hunks; this closeout
did not rewrite unrelated visual semantics to silence a whole-file scanner.

## Closeout boundary

The reproducible preview showcase, current-source development install, service
health, retained-Pi deterministic smokes, and blocked foreground check are
separate receipts. The README deliberately publishes only the privacy-safe
fixture scenes. Nothing here upgrades the repository to release-ready status.
