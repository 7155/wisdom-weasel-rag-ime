# Cross-Platform Frontend Synchronization

## Goal

Keep macOS and Linux behavior synchronized without forcing the two platforms to
share candidate-window UI code. The shared product behavior lives in the sidecar
contract and candidate lifecycle; platform adapters only map native input-method
state to that contract.

## Shared Architecture

```text
macOS Squirrel adapter       Linux Fcitx5/Rime adapter
          \                         /
           \                       /
            -> RimeSidecarRequest ->
              Python sidecar
                /rime-suggest
                /rime-select
              PredictionManager
              SuggestionCompiler
              LocalSqliteCoreClient / JsonCommandCoreClient
            -> RimeSidecarResponse ->
           /                       \
          /                         \
macOS SquirrelPanel           Fcitx5 candidate UI
```

## Shared Contract Surface

The following concepts must remain platform-neutral:

- Rime snapshot: raw input, preedit, commit preview, candidates, comments,
  labels, highlighted index, page, and last-page state.
- `displayCandidates`: one ordered list of visible rows.
- `selectionAction`: `select_rime_candidate` or `commit_side_candidate`.
- `selectionKey` and `selectionRank`: keyboard routing and feedback rank.
- `predictionSession`: hidden/raw/anchor/post-commit/prefix-constrained
  lifecycle metadata.
- `triggerDecision`: whether model/RAG lanes should run for the current context.
- `/rime-select`: selected side candidate plus `shownCandidates` for
  skipped-higher feedback.

## Platform Ownership

| Area | macOS | Linux | Shared? |
| --- | --- | --- | --- |
| Composition engine | Squirrel / librime | Fcitx5-Rime / librime | No |
| Candidate UI drawing | SquirrelPanel | Fcitx5 candidate UI | No |
| Sidecar request schema | Swift Codable models | Linux adapter models | Yes |
| RAG/model/memory ranking | Python sidecar | Python sidecar | Yes |
| Prediction lifecycle | Sidecar + platform clear signals | Sidecar + platform clear signals | Yes |
| Feedback/frequency | `/rime-select` | `/rime-select` | Yes |
| Service manager | LaunchAgent | systemd user service | No |
| Doctor probes | macOS scripts | Linux scripts | Contract should match |

## Synchronization Rules

1. Contract changes land first in Python payload handling and documentation.
2. macOS and Linux adapters then update their native model structs.
3. Both adapters must preserve normal Rime selection behavior for Rime rows.
4. Side rows must be committed through the shared `/rime-select` path.
5. Late sidecar results are invalid unless the active request fingerprint still
   matches the platform context.
6. Empty or stale prediction sessions must clear side candidates before digits
   or space can be captured by old AI rows.
7. English, code, path, URL, and raw passthrough input are protected Rime lanes;
   stale AI candidates must not remain visible there.

## Shared Acceptance Matrix

Every frontend implementation should satisfy these cases against the same
sidecar payload semantics:

| Case | Expected behavior |
| --- | --- |
| First-word pinyin with Rime candidates | Rime rows first; side candidates only if trigger policy allows them. |
| Dirty raw pinyin with Rime candidates | Model does not freely decode raw input; semantic basis is Rime context. |
| Post-commit continuation | Short prediction-only session may show model/RAG/memory rows. |
| No candidates / stale response | Prediction panel clears and digit keys are not captured. |
| Prefix-constrained continuation | Candidate pool may be reused only while prefix and context fingerprint match. |
| English/code/path/URL | Rime/Wanxiang protected lane dominates; stale side candidates are hidden. |
| Side-candidate selection | Commit text and call `/rime-select` with `shownCandidates`. |
| Rime-candidate selection | Route to librime only; do not call `/rime-select`. |

## Branch Policy

Linux frontend work should be developed in a platform branch, but shared sidecar
or contract changes should remain small and independently reviewable. A useful
commit sequence is:

1. Documentation and contract notes.
2. Linux systemd user service and doctor scripts.
3. Minimal Fcitx5 adapter payload generation.
4. Candidate display and selection routing.
5. Feedback and acceptance probes.
