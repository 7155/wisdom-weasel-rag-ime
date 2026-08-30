# Project Outcomes

Updated: 2026-08-21

This file is the bounded project focus set, not a task database. Domain status
is one of `proposed`, `active`, `blocked`, `completed`, or `cancelled`.
Runtime activity, owners, worktree state, and Tool progress are read from
their authoritative projections.

## Evidence Boundary

These entries distinguish source/test progress, installed development evidence,
foreground acceptance, and distribution acceptance. Git cleanliness, installed
commit identity, Runtime state, and release gates must be checked live;
this document cannot make those mechanical facts true. Machine-readable
release evidence remains in `release/product-status.json` and the release audit.

## Current Focus

| ID | User result | Status | Current evidence boundary | Next acceptance frontier |
| --- | --- | --- | --- | --- |
| O1 | Session can work reliably for a long time | active | The installed Luna canary passed public activity, native Steer order, Stop, Tool failure closure, refresh, and an 8/8 bounded Tool-result round; the real browser projected `stopping` in 35 ms | Long-duration soak and repeated compaction/recovery on real development work |
| O2 | Room completes a real collaboration by composing Pi Sessions | active | The installed Luna Room canary used two ordinary Pi Sessions, completed one `room_partner` child, returned its event/result, emitted exactly one Root final, stopped a second live Tool turn, and refreshed without active ghosts | A useful self-hosted project change with organically chosen Partner/Tool Agent work and retained evidence |
| O3 | A parent Session can use configurable private Tool Agents | active | Current source supports bounded child events/results, read/write choice, model/thinking override, and same-tree peer calls | Prove a useful live parent/child run, then raise capacity through bounded event/UI/resource budgets rather than more Kernel state |
| O4 | PAW can develop itself through a bounded context and Skill harness | active | Core Skills and the source-isolated `pawos-app-builder` exist; the first Extension App binds a co-versioned Pi Package and SGG suite without putting business code in the shell | Install, apply the Package, then verify a foreground 掌柜问数 conversation and uninstall/restore |
| O5 | Control Center truthfully renders Session and Room state | active | Shared reducers cover pseudo-empty Room tasks, task details/progress, terminal Tool cards, compact Tool/thinking UI, Stop/Steer order, rich HTML output, refresh recovery, and package-market previews; current source also deduplicates Room/Pi user mirrors and labels partial context restoration instead of a false completed round | Installed browser check for Room/Pi history deduplication and recent/full restoration, then no empty active Root, white HTML preview, or ghost running turn after refresh |
| O6 | Memory and Knowledge provide governed, explainable context | active | Local stores, curation, retrieval, evaluation, and management surfaces exist; recent commits refined daily activity and Project Field evidence | Keep Memory/Knowledge authority separate, verify retrieval quality on frozen evaluations, and finish product-facing acceptance without widening Session bootstrap |
| O7 | The macOS input experience is correct in real foreground apps | active | Source, sidecar, patched Squirrel, and automated checks exist; the older status snapshot records partial foreground evidence | Fresh foreground matrix for composition, deletion, app switch, follow-up, RAG/memory selection, Accessibility, and voice |
| O8 | A public macOS release is reproducible and distributable | blocked | Public source and engineering build paths exist | Clean scoped source, current release manifest, candidate-quality sign-off, Developer ID signing, notarization, stapling, clean-machine installation, and accepted foreground evidence |
| O9 | PAW OS reuses selected Tutti frontend patterns while Pi/Gateway retain Runtime ownership | active | A selectable PAW OS shell provides Wayfinder, grouped App identities, windows, Dock, Launchpad, Mission Control, and three reference-aligned themes while the legacy shell remains available; Browser maps its visible tab and address bar to the governed PAW `deviceId + tabId` command path | Finish Files and Terminal adapters, redesign each remaining App surface, then run installed-runtime and multi-window acceptance before cutover |

## O1 — Long-Running Session

Acceptance requires all of the following on one current Runtime/build:

- Luna shows useful text or a public thinking summary without an indefinitely
  empty “thinking” card. Five seconds is an experience target, not a forced
  timeout.
- Steer uses Pi's native Session path and the user message appears before its
  queued/processing event.
- Stop immediately projects `stopping`, covers the pre-turn admission window,
  and reaches a real terminal or escalated cancellation state.
- Every Tool success, rejection, failure, and cancellation closes its Tool card.
- Refresh reconstructs durable history plus only the real live tail; it cannot
  create a zero-message ghost turn.
- Public Tool results stay within one round-level budget rather than multiplying
  a per-Tool limit.

The 2026-08-16 installed development Runtime passed this sequence: first public
activity in 6.4 seconds; correct Steer ordering; the browser
projected `stopping` in 35 ms; Runtime Stop terminated in 384 ms; the failed
Tool closed; refresh had no active ghost; and eight bounded Tool calls produced
eight terminal events with public payloads capped at 660 bytes. This is
current-build acceptance, not yet a multi-day soak or public-release claim.

## O2 — Lightweight Room

The accepted design is one Facilitator Session plus zero or more visible Partner
Sessions. Partners may use private Tool Agents. Pi owns each Session; Room owns
collaboration identity, explicit dispatch, ordered public events, cancellation
fan-out, and one terminal Root.

The installed Luna canary proves the lifecycle on the current development
Runtime: two ordinary Luna Sessions, Facilitator-owned dispatch, one Partner
child start/completion, Partner result return, one Root final, a second live
Tool turn stopped with one `aborted` terminal, and a stable refresh. The next
frontier is useful self-hosted work rather than another scripted lifecycle.

## O3 — Tool Agent Capacity

Tool Agents are the parent Session's private hands, not miniature Room members.
The parent selects their task, context refs, Skills, model/model card, thinking,
access, tools, workspace, and peer-call permission. A child result has
`evidence_only` authority until its parent verifies and integrates it.

Current conservative parallel/depth limits are an implementation boundary, not
the product goal. Scale should come from event pagination, bounded result
retention, cancellation, resource budgets, and a compact UI—not a heavier Room
Kernel.

## O4 — Self-Hosting Harness

The root bootstrap and eight core Skills are the first self-hosting layer. The
background organizer keeps accepted documents linked and compact, while active
Agents own the meaning they produce. A live self-hosting canary should verify
that a new Session reads only the current Outcome and selected refs, chooses no
unnecessary Skill, performs a real change, and returns a bounded `AgentResult`.

The ability market is a Pi Package surface. It accepts npm, Git, local, and
catalog sources; prepares and inspects them without model approval; asks for
product confirmation only before state mutation; and records installed
versions for update and rollback. Pi loads Package resources into new
Sessions. The `plugin-creator` Skill searches and reuses first, creates a
minimal Package only when the capability is absent, and stops at the same
product confirmation boundary. The 2026-08-16 development installation exposed
`piPackages: true`; its active Runtime created and prepared an isolated local
Package with one Skill without mutating real installed-package state.

New projects initialize only when the user invokes Pi's `/init` prompt
template. It inspects the bound workspace and creates or narrowly supplements
the root `AGENTS.md`; Session creation never writes project files.

## O5–O8 — Product Surfaces And Release

These Outcomes remain visible because Session/Room success cannot justify a
false whole-product claim. UI projections must use Runtime truth; governed
Memory/Knowledge must keep provenance and evaluation; native adapters require
foreground evidence; release remains blocked until the machine-readable gates
and distribution evidence are current.

## Condensed History

Older Kernel-heavy Room plans, mandatory quality/review stages, per-task
worktree ceremony, and giant self-contained review bundles are historical
evidence, not current workflow. Persisted migrations remain append-only;
source paths are deleted only after current consumers are proven absent.
