# PAWOS Requirement Status

This document answers “which requirements are complete?” without changing the
meaning ledger set indexed by [PAWOS_REQUIREMENTS.md](PAWOS_REQUIREMENTS.md). The
thirty requirement volumes own user meaning; this index owns explicit assessment and evidence
links. Runtime, Git, installation, and foreground state remain authoritative in
their own projections and receipts.

## Reading rules

- A requirement marked `current` in the meaning ledger is active/current
  semantics. It is **not** an implementation status and never implies
  `complete`.
- `assessment=complete` is allowed only when `runsVerdict=passed`,
  `requirementVerdict=satisfied`, every explicit `requiredEvidenceLevels` value
  has a linked valid receipt, and at least one evidence receipt is linked. The
  two verdicts answer different questions: “did the checked path
  run?” and “did the observed result satisfy this exact requirement?”
- Markdown checkboxes, code diffs, test filenames, screenshots, builds, Agent
  prose, or silence never update this index automatically.
- Evidence levels are separate proof boundaries. A higher level must be
  recorded only when that exact boundary was observed; source/test/build proof
  must not be promoted into install, Runtime, or foreground proof.
- Every edit must retain `UR-001` through the current final requirement with no
  gaps across the indexed volumes. Run `python3 scripts/check_pawos_requirement_status.py`
  after document-set changes. A source hash is only a legacy diagnostic receipt;
  it does not block product work, Room completion, or a truthful final result.

## Evidence levels

| Level | Name | What it can prove |
| --- | --- | --- |
| E1 | Source | Owning source/contract exists at the recorded revision. |
| E2 | Test | The named executable check passed in its stated scope. |
| E3 | Build | The named build/package step succeeded for the recorded source. |
| E4 | Install | The recorded artifact was installed through the named product path. |
| E5 | Runtime | The installed/current Runtime produced the recorded authoritative event or state. |
| E6 | Foreground | A real user-visible foreground interaction satisfied the recorded acceptance. |

Evidence levels describe scope, not a completion ladder. For example, E2 does
not prove E4–E6, and a screenshot without an authoritative run identity does
not prove the Runtime path.

## Current honest summary — 2026-09-04

| Scope | Current indexed result | Boundary / next action |
| --- | --- | --- |
| All requirements | `235 unassessed`, `6 complete`, `7 receipts` | `UR-150`–`UR-152` and the bounded conversation-stability requirements `UR-237`–`UR-239` are closed; other requirements retain their prior status. |
| Current P0 requirements | 196 controlling P0 entries: `193 unassessed`, `3 complete` | Only `UR-237`–`UR-239` have fresh scoped closeout receipts in this P0 set. |
| Recent conversation/UI/final-delivery requirements | `UR-133`–`UR-149`, `UR-153`–`UR-236`, `UR-240`–`UR-241` remain `unassessed`; `UR-150`–`UR-152` and `UR-237`–`UR-239` are `complete` | Conversation closure is bounded to exactly-once admission/rendering, transport recovery, and Memory/conflict isolation. |
| Install / Runtime / foreground | No E4 receipt; E5/E6 are linked only to `UR-237`–`UR-239` | E5/E6 came from an isolated source Gateway and real PAWOS browser foreground; they do not claim an installed-app update. |

This conservative baseline is intentional. It does not say that no code exists;
it says 235 requirements have not yet been individually assessed against fresh,
linked evidence in this index. The conversation receipts do not promote the
source canary to E4 installation evidence or close the separate Eval/RAG work.

## Updating one requirement

1. Add immutable evidence objects under `receipts`, each with its exact E1–E6
   level, timestamp, owner, bounded claim, artifact references, and a
   `sha256:<64 lowercase hex>` receipt hash.
2. Replace that requirement's empty override with explicit `assessment`, both
   verdicts, `requiredEvidenceLevels`, `evidenceRefs`, owner, timestamp, note,
   and (unless complete) the next action. Choose required levels from the
   requirement's actual acceptance boundary; the checker does not infer them.
3. Use `complete` only when the run passed and the precise requirement was
   satisfied. A partial implementation stays `in_progress`; a passing test with
   missing foreground acceptance stays non-complete.
4. Run the checker after changing the indexed document set. Record its bounded
   structural result when useful; it validates coverage and linkage, not the
   truth of an external observation and never becomes a product gate.

## Machine-readable status receipt

The JSON block below is the canonical status payload. Empty per-requirement
objects inherit the conservative defaults; they are explicit coverage entries,
not inferred status.

<!-- PAWOS_REQUIREMENT_STATUS_JSON_BEGIN -->
```json
{
  "schemaVersion": "pawos.requirement-status.v1",
  "sourceReceipt": {
    "path": "PAWOS_REQUIREMENTS.md",
    "sha256": "sha256:949bdee90e213f2a94bf4b0f4c3bbe3ecea30002ec97e65f8eb3a11c7beed902",
    "recordedAt": "2026-08-29T01:32:03+08:00",
    "owner": "PAWOS requirements status index"
  },
  "evidenceLevelLabels": {
    "E1": "Source",
    "E2": "Test",
    "E3": "Build",
    "E4": "Install",
    "E5": "Runtime",
    "E6": "Foreground"
  },
  "defaults": {
    "assessment": "unassessed",
    "runsVerdict": "unverified",
    "requirementVerdict": "unverified",
    "evidenceRefs": []
  },
  "receipts": {
    "RCP-PAWOS-SHOWCASE-SOURCE-20260827": {
      "level": "E1",
      "recordedAt": "2026-08-27T04:52:28+08:00",
      "owner": "PAWOS final showcase Goal",
      "claim": "The current-source capability decision, Demo contract, README images and command, and explicit E1-E6 evidence boundaries are present.",
      "artifactRefs": [
        "README.md#pawos-in-one-tour",
        "control-center-web/docs/pawos/PAWOS_SHOWCASE.md",
        "control-center-web/docs/pawos/PAWOS_REQUIREMENTS.md#ur-150--ur-152",
        "scripts/capture_pawos_showcase.sh",
        "scripts/write_pawos_showcase_manifest.mjs"
      ],
      "sha256": "sha256:772eda8e0da3a83b20b3627aeac8d20d4dccd044b64e7e86bbfc38a1f67331a9"
    },
    "RCP-PAWOS-SHOWCASE-CAPTURE-20260827": {
      "level": "E2",
      "recordedAt": "2026-08-27T05:18:44+08:00",
      "owner": "PAWOS final showcase Goal",
      "claim": "The documented command passed 1/1 in the Goal worktree and in a disposable clean checkout after a frozen-lockfile install, generating three named 1440x900 WebP images and a playable VP8 WebM from public fixtures.",
      "artifactRefs": [
        "scripts/capture_pawos_showcase.sh",
        "control-center-web/e2e/pawos-showcase.capture.ts",
        "control-center-web/playwright.showcase.config.ts",
        "assets/showcase/showcase-manifest.json",
        "control-center-web/output/showcase/pawos-showcase.webm (ignored local artifact)"
      ],
      "sha256": "sha256:e8c005b168742cbf50ed9a4236edb89a767cb0cca19680fba8c4c845f57900f6"
    },
    "RCP-PAWOS-CONVERSATION-SOURCE-20260904": {
      "level": "E1",
      "recordedAt": "2026-09-04T01:55:31+08:00",
      "owner": "PAW conversation stability Goal",
      "claim": "The source now preserves exact client and turn identity, distinguishes admission outcomes, commits transport cursors only after delivery, repairs snapshot gaps, and prevents ambiguous Memory replay.",
      "artifactRefs": [
        "control-center-web/src/contracts/agent-reducer.ts",
        "control-center-web/src/paw-os/apps/PawAgentHome.tsx",
        "control-center-web/src/paw-os/apps/PawSessionWorkspace.tsx",
        "control-center-web/src/features/agent/runtime/use-agent-live-session.ts",
        "control-center-web/src/platform/sse.ts",
        "control-center-web/src/platform/http-transport.ts",
        "control-center-web/src/platform/native-transport.ts",
        "rag_ime/agent_protocol.py",
        "rag_ime/pi_runtime_v2.py",
        "rag_ime/memory_model_executor.py",
        "control-center-web/docs/pawos/requirements/PAWOS_REQUIREMENT_EVIDENCE.md#2026-09-04--对话稳定性修复结果真实-case-与独立复核"
      ],
      "sha256": "sha256:949d559ce11a72f7f7cc6caadf3bf43b893b9e646e7ff5baf5e46c34226adc43"
    },
    "RCP-PAWOS-CONVERSATION-TESTS-20260904": {
      "level": "E2",
      "recordedAt": "2026-09-04T01:55:31+08:00",
      "owner": "PAW conversation stability Goal",
      "claim": "Focused and broad frontend, Memory, Pi identity, replay, conflict, cancellation, and recovery checks passed; generated contracts, import boundaries, route ownership, and diff checks also passed.",
      "artifactRefs": [
        "control-center-web/src/contracts/agent-reducer.test.ts",
        "control-center-web/src/paw-os/apps/PawAgentHome.test.tsx",
        "control-center-web/src/paw-os/apps/PawSessionWorkspace.test.tsx",
        "control-center-web/src/features/agent/runtime/use-agent-live-session.test.tsx",
        "control-center-web/src/platform/http-transport.test.ts",
        "control-center-web/src/platform/native-transport.test.ts",
        "control-center-web/src/platform/sse.test.ts",
        "tests/test_memory_model_executor.py",
        "tests/test_pi_runtime_v2.py",
        "python3 scripts/check_import_boundaries.py",
        "python3 scripts/check_route_ownership.py"
      ],
      "sha256": "sha256:1230d969fea7acef416d5bcc12fb083d2748b90e335224099a4edd38ee1d84c2"
    },
    "RCP-PAWOS-CONVERSATION-BUILD-20260904": {
      "level": "E3",
      "recordedAt": "2026-09-04T01:55:31+08:00",
      "owner": "PAW conversation stability Goal",
      "claim": "The production-channel HTTP-only PAWOS frontend build completed from the checked source: 4492 modules in 7.18 seconds, with only the existing large-chunk warnings.",
      "artifactRefs": [
        "control-center-web/dist",
        "env VITE_CONTROL_TRANSPORT=http VITE_BUILD_CHANNEL=production pnpm build"
      ],
      "sha256": "sha256:9d07a0184a2725ac7bb3700c1ce080447c93f43de74b590a0907e76b7b75f011"
    },
    "RCP-PAWOS-CONVERSATION-RUNTIME-20260904": {
      "level": "E5",
      "recordedAt": "2026-09-04T01:55:31+08:00",
      "owner": "PAW conversation stability Goal",
      "claim": "The isolated source Gateway converged restart replay and two consecutive foreground turns to exact durable bindings and settlements without increasing message count or cursor on idempotent replay.",
      "artifactRefs": [
        "runtime-session:agent:755142dd-2056-4789-b8d7-f525d424a27a",
        "runtime-session:agent:8e4d810f-e813-400d-aabc-d2fd1fb608d2",
        "turn:2945eaa7-8dbc-452d-a59d-7b26518b3b1c",
        "turn:ff62e216-9c37-45ae-9c81-1c4c8af395de",
        "turn:54c4e6d3-d22a-404c-8e09-597021a99a65",
        "durable-jsonl-sha256:71e4a408de56347b7dac08c28035471ff86f5570e206be45fbdf510c75c0b20b",
        "control-center-web/docs/pawos/requirements/PAWOS_REQUIREMENT_EVIDENCE.md#2026-09-04--对话稳定性修复结果真实-case-与独立复核"
      ],
      "sha256": "sha256:319e37b5d5dc136aa7358087db5ffa63dd109015ed88109697b8aba312e01b68"
    },
    "RCP-PAWOS-CONVERSATION-FOREGROUND-20260904": {
      "level": "E6",
      "recordedAt": "2026-09-04T01:55:31+08:00",
      "owner": "PAW conversation stability Goal",
      "claim": "A real PAWOS browser foreground showed the first prompt and a known-Session follow-up exactly once before and after refresh, with zero incomplete or missing-reply cards and zero browser console errors.",
      "artifactRefs": [
        "output/playwright/pawos-conversation-stability-before-refresh.png",
        "output/playwright/pawos-conversation-stability-after-refresh.png",
        "output/playwright/pawos-known-session-before-refresh.png",
        "output/playwright/pawos-known-session-after-refresh.png",
        "control-center-web/docs/pawos/requirements/PAWOS_REQUIREMENT_EVIDENCE.md#2026-09-04--对话稳定性修复结果真实-case-与独立复核"
      ],
      "sha256": "sha256:c782058b49215e7b029bbff01915be9395162ba5453512ce0632a7ea039197e5"
    }
  },
  "requirements": {
    "UR-001": {},
    "UR-002": {},
    "UR-003": {},
    "UR-004": {},
    "UR-005": {},
    "UR-006": {},
    "UR-007": {},
    "UR-008": {},
    "UR-009": {},
    "UR-010": {},
    "UR-011": {},
    "UR-012": {},
    "UR-013": {},
    "UR-014": {},
    "UR-015": {},
    "UR-016": {},
    "UR-017": {},
    "UR-018": {},
    "UR-019": {},
    "UR-020": {},
    "UR-021": {},
    "UR-022": {},
    "UR-023": {},
    "UR-024": {},
    "UR-025": {},
    "UR-026": {},
    "UR-027": {},
    "UR-028": {},
    "UR-029": {},
    "UR-030": {},
    "UR-031": {},
    "UR-032": {},
    "UR-033": {},
    "UR-034": {},
    "UR-035": {},
    "UR-036": {},
    "UR-037": {},
    "UR-038": {},
    "UR-039": {},
    "UR-040": {},
    "UR-041": {},
    "UR-042": {},
    "UR-043": {},
    "UR-044": {},
    "UR-045": {},
    "UR-046": {},
    "UR-047": {},
    "UR-048": {},
    "UR-049": {},
    "UR-050": {},
    "UR-051": {},
    "UR-052": {},
    "UR-053": {},
    "UR-054": {},
    "UR-055": {},
    "UR-056": {},
    "UR-057": {},
    "UR-058": {},
    "UR-059": {},
    "UR-060": {},
    "UR-061": {},
    "UR-062": {},
    "UR-063": {},
    "UR-064": {},
    "UR-065": {},
    "UR-066": {},
    "UR-067": {},
    "UR-068": {},
    "UR-069": {},
    "UR-070": {},
    "UR-071": {},
    "UR-072": {},
    "UR-073": {},
    "UR-074": {},
    "UR-075": {},
    "UR-076": {},
    "UR-077": {},
    "UR-078": {},
    "UR-079": {},
    "UR-080": {},
    "UR-081": {},
    "UR-082": {},
    "UR-083": {},
    "UR-084": {},
    "UR-085": {},
    "UR-086": {},
    "UR-087": {},
    "UR-088": {},
    "UR-089": {},
    "UR-090": {},
    "UR-091": {},
    "UR-092": {},
    "UR-093": {},
    "UR-094": {},
    "UR-095": {},
    "UR-096": {},
    "UR-097": {},
    "UR-098": {},
    "UR-099": {},
    "UR-100": {},
    "UR-101": {},
    "UR-102": {},
    "UR-103": {},
    "UR-104": {},
    "UR-105": {},
    "UR-106": {},
    "UR-107": {},
    "UR-108": {},
    "UR-109": {},
    "UR-110": {},
    "UR-111": {},
    "UR-112": {},
    "UR-113": {},
    "UR-114": {},
    "UR-115": {},
    "UR-116": {},
    "UR-117": {},
    "UR-118": {},
    "UR-119": {},
    "UR-120": {},
    "UR-121": {},
    "UR-122": {},
    "UR-123": {},
    "UR-124": {},
    "UR-125": {},
    "UR-126": {},
    "UR-127": {},
    "UR-128": {},
    "UR-129": {},
    "UR-130": {},
    "UR-131": {},
    "UR-132": {},
    "UR-133": {},
    "UR-134": {},
    "UR-135": {},
    "UR-136": {},
    "UR-137": {},
    "UR-138": {},
    "UR-139": {},
    "UR-140": {},
    "UR-141": {},
    "UR-142": {},
    "UR-143": {},
    "UR-144": {},
    "UR-145": {},
    "UR-146": {},
    "UR-147": {},
    "UR-148": {},
    "UR-149": {},
    "UR-150": {
      "assessment": "complete",
      "runsVerdict": "passed",
      "requirementVerdict": "satisfied",
      "evidenceRefs": [
        "RCP-PAWOS-SHOWCASE-SOURCE-20260827",
        "RCP-PAWOS-SHOWCASE-CAPTURE-20260827"
      ],
      "requiredEvidenceLevels": [
        "E1",
        "E2"
      ],
      "owner": "PAWOS final showcase Goal",
      "updatedAt": "2026-08-27T04:52:28+08:00",
      "note": "Current source and fresh checks selected Agent Session plus Multi-Agent Room; optional adapters were not promoted without fresh foreground evidence."
    },
    "UR-151": {
      "assessment": "complete",
      "runsVerdict": "passed",
      "requirementVerdict": "satisfied",
      "evidenceRefs": [
        "RCP-PAWOS-SHOWCASE-SOURCE-20260827",
        "RCP-PAWOS-SHOWCASE-CAPTURE-20260827"
      ],
      "requiredEvidenceLevels": [
        "E1",
        "E2"
      ],
      "owner": "PAWOS final showcase Goal",
      "updatedAt": "2026-08-27T04:52:28+08:00",
      "note": "The repository command passed after a clean clone, frozen-lockfile dependency install, and Playwright Chromium install check; it generated the same three named scenes and a playable recording without personal data."
    },
    "UR-152": {
      "assessment": "complete",
      "runsVerdict": "passed",
      "requirementVerdict": "satisfied",
      "evidenceRefs": [
        "RCP-PAWOS-SHOWCASE-SOURCE-20260827",
        "RCP-PAWOS-SHOWCASE-CAPTURE-20260827"
      ],
      "requiredEvidenceLevels": [
        "E1",
        "E2"
      ],
      "owner": "PAWOS final showcase Goal",
      "updatedAt": "2026-08-27T04:52:28+08:00",
      "note": "README now presents the strongest current PAWOS scenes with fixture provenance, a runnable command, privacy limits, and explicit non-claims for install, Runtime, foreground, signing, notarization, and release readiness."
    },
    "UR-153": {},
    "UR-154": {},
    "UR-155": {},
    "UR-156": {},
    "UR-157": {},
    "UR-158": {},
    "UR-159": {},
    "UR-160": {},
    "UR-161": {},
    "UR-162": {},
    "UR-163": {},
    "UR-164": {},
    "UR-165": {},
    "UR-166": {},
    "UR-167": {},
    "UR-168": {},
    "UR-169": {},
    "UR-170": {},
    "UR-171": {},
    "UR-172": {},
    "UR-173": {},
    "UR-174": {},
    "UR-175": {},
    "UR-176": {},
    "UR-177": {},
    "UR-178": {},
    "UR-179": {},
    "UR-180": {},
    "UR-181": {},
    "UR-182": {},
    "UR-183": {},
    "UR-184": {},
    "UR-185": {},
    "UR-186": {},
    "UR-187": {},
    "UR-188": {},
    "UR-189": {},
    "UR-190": {},
    "UR-191": {},
    "UR-192": {},
    "UR-193": {},
    "UR-194": {},
    "UR-195": {},
    "UR-196": {},
    "UR-197": {},
    "UR-198": {},
    "UR-199": {},
    "UR-200": {},
    "UR-201": {},
    "UR-202": {},
    "UR-203": {},
    "UR-204": {},
    "UR-205": {},
    "UR-206": {},
    "UR-207": {},
    "UR-208": {},
    "UR-209": {},
    "UR-210": {},
    "UR-211": {},
    "UR-212": {},
    "UR-213": {},
    "UR-214": {},
    "UR-215": {},
    "UR-216": {},
    "UR-217": {},
    "UR-218": {},
    "UR-219": {},
    "UR-220": {},
    "UR-221": {},
    "UR-222": {},
    "UR-223": {},
    "UR-224": {},
    "UR-225": {},
    "UR-226": {},
    "UR-227": {},
    "UR-228": {},
    "UR-229": {},
    "UR-230": {},
    "UR-231": {},
    "UR-232": {},
    "UR-233": {},
    "UR-234": {},
    "UR-235": {},
    "UR-236": {},
    "UR-237": {
      "assessment": "complete",
      "runsVerdict": "passed",
      "requirementVerdict": "satisfied",
      "evidenceRefs": [
        "RCP-PAWOS-CONVERSATION-SOURCE-20260904",
        "RCP-PAWOS-CONVERSATION-TESTS-20260904",
        "RCP-PAWOS-CONVERSATION-BUILD-20260904",
        "RCP-PAWOS-CONVERSATION-RUNTIME-20260904",
        "RCP-PAWOS-CONVERSATION-FOREGROUND-20260904"
      ],
      "requiredEvidenceLevels": ["E1", "E2", "E3", "E5", "E6"],
      "owner": "PAW conversation stability Goal",
      "updatedAt": "2026-09-04T01:55:31+08:00",
      "note": "First and known-Session prompts converge by exact identity, appear once immediately, retain one terminal result across refresh, and show no ghost failure card in the isolated real foreground. E4 was intentionally not required because this Goal did not authorize installation."
    },
    "UR-238": {
      "assessment": "complete",
      "runsVerdict": "passed",
      "requirementVerdict": "satisfied",
      "evidenceRefs": [
        "RCP-PAWOS-CONVERSATION-SOURCE-20260904",
        "RCP-PAWOS-CONVERSATION-TESTS-20260904",
        "RCP-PAWOS-CONVERSATION-BUILD-20260904",
        "RCP-PAWOS-CONVERSATION-RUNTIME-20260904",
        "RCP-PAWOS-CONVERSATION-FOREGROUND-20260904"
      ],
      "requiredEvidenceLevels": ["E1", "E2", "E3", "E5", "E6"],
      "owner": "PAW conversation stability Goal",
      "updatedAt": "2026-09-04T01:55:31+08:00",
      "note": "HTTP admission, SSE delivery, snapshot repair, cursor replay, durable transcript recovery, and Host restart converged without skipped events, terminal regression, or duplicate public messages in the checked source Runtime."
    },
    "UR-239": {
      "assessment": "complete",
      "runsVerdict": "passed",
      "requirementVerdict": "satisfied",
      "evidenceRefs": [
        "RCP-PAWOS-CONVERSATION-SOURCE-20260904",
        "RCP-PAWOS-CONVERSATION-TESTS-20260904",
        "RCP-PAWOS-CONVERSATION-BUILD-20260904",
        "RCP-PAWOS-CONVERSATION-RUNTIME-20260904",
        "RCP-PAWOS-CONVERSATION-FOREGROUND-20260904"
      ],
      "requiredEvidenceLevels": ["E1", "E2", "E3", "E5", "E6"],
      "owner": "PAW conversation stability Goal",
      "updatedAt": "2026-09-04T01:55:31+08:00",
      "note": "Structured conflicts remain retryable, ambiguous Memory admission never replays automatically, ordinary conversations remain intact under injected Memory failures, and the two proven no-consumer error branches were removed or bypassed."
    },
    "UR-240": {},
    "UR-241": {}
  }
}
```
<!-- PAWOS_REQUIREMENT_STATUS_JSON_END -->
