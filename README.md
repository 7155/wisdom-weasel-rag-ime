# Wisdom Weasel RAG IME

An experimental, local-first intelligent input method for macOS. It keeps
normal Pinyin composition inside Rime/Squirrel, then adds local completion,
retrieval-backed memory, and an explicit Active RAG action after text is
committed.

> [!IMPORTANT]
> This is a research prototype, not a packaged production IME. The repository
> is public for inspection and collaboration, but the release gate is still
> blocked by foreground acceptance and completion-quality work.

## Product Route

The supported product route is the macOS Rime/Squirrel candidate-layer adapter
plus the Python sidecar. The adapter is delivered as a pinned Squirrel patch.
The obsolete independent InputMethodKit prototype has been removed so there is
one input-method frontend and one source of truth for foreground behavior.

Squirrel is also no longer the owner of model, RAG, memory, or feedback logic.
The versioned [Generic Frontend Gateway](docs/frontend-adapter-boundary.md)
isolates those shared backend contracts behind engine-neutral frontend,
session, privacy, input-engine, and native-candidate fields. Squirrel remains
the only real frontend in this repository today; no Fcitx5, IBus, Linux, or
other frontend runtime is claimed.

```text
Pinyin composition
  -> Rime/librime candidates and native user-dictionary ranking
  -> Squirrel commits selected text

Post-commit assistance
  -> trusted foreground-context snapshot
  -> local MiniMind completion (up to three alternatives)
  -> local Hybrid RAG and curated memory
  -> source-aware overlay
  -> Tab or Option+number acceptance

Explicit Active RAG
  -> user invokes the configured shortcut on selected text
  -> local retrieval assembles evidence
  -> optional configured DeepSeek-compatible provider generates one result
  -> user reviews before replacement

Explicit knowledge workbench
  -> user asks for a knowledge answer, long-form draft, recall, or database organization
  -> local SQLite RAG returns traceable evidence
  -> DeepSeek generates a multi-paragraph answer outside the keystroke path
  -> optional Notion Worker + Custom Agent adds authorized workspace knowledge
  -> stale remote results are rejected before local/remote synthesis

Streaming voice input
  -> hold Option+Space in any supported text field
  -> a separate native agent captures 16 kHz mono PCM in memory
  -> optional bounded hotwords come only from the user's explicit Control Center list
  -> Doubao streaming ASR 2.0 returns cumulative partial transcripts
  -> the volatile transcript is replaced in place at the current cursor
  -> releasing the shortcut sends the final frame and commits Doubao's final text
```

## Current Capabilities

| Area | Current behavior |
| --- | --- |
| Pinyin | Rime owns composition, sentence generation, fuzzy Pinyin, and native user-dictionary learning. A public-safe 10-case deployed-librime regression currently passes Top-1 at 10/10, including `yon/yong -> 用` and common phrases. The patched post-selection feedback route remains `backend_only` until a fresh foreground selection trace passes. |
| Local completion | MLX, local Ollama, and loopback OpenAI-compatible runtimes share one validated registry/lifecycle boundary. The current MiniMind-derived checkpoint is fast enough and reliably returns three branches, but its semantic quality gate and retraining signoff have not passed. |
| Hybrid RAG | Local SQLite retrieval combines lexical, tag, time-book, and feedback signals. Vector lanes are disabled when no embedding provider is available. |
| Memory | Local events, stable memories, feedback, tombstones, anti-echo checks, and reviewed cleanup flows. |
| Active RAG | Explicit selected-text workflow with local evidence and an optional remote DeepSeek-compatible route. It is never part of passive per-keystroke prediction. |
| UI | The patched Squirrel native overlay has a v3 working-tree polish pass with compact material, source tints/icons, shortcut plates, hover/accept/streaming motion, bounded TTL, and Reduce Motion handling. Static/build checks are not a real foreground screenshot, so visual acceptance remains pending. `RagImeControl` is the one settings/diagnostics app; the legacy browser console has been removed and the voice agent is headless. |
| Knowledge workbench | Explicit local-RAG + DeepSeek knowledge answers, long-form writing, recall, and review-only database organization. Optional Notion submission and polling are separate, observable gates. |
| Voice input | The headless native agent, Keychain route, and a real Doubao PCM probe work. Its v3 status reports network state, first-partial/final latency, PCM/revision counts, discarded frames, and only the enabled hotword count without storing audio or transcript text. Request-level hotwords are optional, bounded, explicitly entered in the one Control Center, and never derived from the private Rime user dictionary. Foreground behavior stays `backend_only` until a user-authorized microphone run. |
| Observability | Redacted runtime status, trigger decisions, candidate score explanations, context provenance, and foreground traces. |

The current MiniMind runtime is fast enough for the backend latency/count gate,
but latency and three valid strings are not the same as relevance. The
checkpoint still produces generic or weak continuations in real contexts, so
the semantic gate, real single-user typing evaluation, and retraining decision
remain open. The runtime abstains on uncertain branches rather than forcing
three suggestions after every commit.

Machine-readable release status lives in
[`docs/product-status.json`](docs/product-status.json). It intentionally keeps
backend readiness separate from real foreground proof.

### Model runtimes

The model registry records two different facts explicitly: the artifact format
(`mlx`, `safetensors`, `gguf`, or `remote`) and the process that can actually
serve it (`mlx`, `ollama`, or local `openai-compatible`). Registering a GGUF no
longer causes the restart script to silently try to load it through MLX.
Registry v3 writes a full content fingerprint for new local artifacts. The MLX
server computes the same fingerprint once at startup, and health/readiness
checks reject a resident model that does not match the selected registry entry.
Legacy v1/v2 short fingerprints remain readable and are reported as
`legacy-unverified` rather than silently rewritten.

```bash
python3 -m rag_ime.model_registry list
python3 -m rag_ime.model_runtime --lane hot --probe
```

- `mlx`: a project-managed resident LaunchAgent on `127.0.0.1:8767`, with
  server timing, seeded branch replay, and batch-candidate capability probing;
- `ollama`: an externally managed local Ollama service and native streaming
  prediction provider;
- `openai-compatible`: an externally managed local endpoint, suitable for
  llama.cpp or another server implementing the local OpenAI contract.

All three runtime choices use the same normalized health, capability, lifecycle,
model-identity, loopback, no-proxy, rollback, and semantic-readiness checks. This is an
engineered serving boundary, not a claim that every registered checkpoint has
passed the product quality gate.

The realtime hot lane is loopback-only for every runtime. Remote providers stay
in explicit Active RAG or offline knowledge workflows and cannot be activated
as a passive per-keystroke model. `scripts/restart_rag_ime_runtime.sh` starts
the managed MLX service only for an MLX deployment; for external runtimes it
first probes the endpoint and refuses to start Sidecar on a dead route.

## Privacy Model

- Passive completion and retrieval are local by default.
- Detected Secure/password fields fail closed before text recording, retrieval, or model
  inference.
- Raw input text is excluded from default traces and diagnostics.
- App or context-group changes invalidate buffered foreground context.
- Remote generation is reserved for an explicit Active RAG action and requires
  user configuration. Selected text and assembled context may leave the machine
  only when that action is invoked.
- Voice input is also explicit. Audio is held in memory and sent to Volcengine
  only while the
  user holds the voice shortcut, and is never added to the RAG or typing-history
  databases. Secure Input, password roles, and detected account fields fail
  closed before the microphone starts. The provider route is governed by
  Volcengine's service terms and data policy.
- Model weights, local databases, personal input history, API keys, built app
  bundles, and machine-specific configuration must not be committed.

This project handles text from every application in which the input method is
enabled. Review the privacy settings and source before using it with sensitive
material.

## Repository Layout

| Path | Purpose |
| --- | --- |
| `rag_ime/` | Python sidecar, runtime config, local memory/RAG core, predictor clients, management API, and CLI. |
| `squirrel-patches/` | Pinned patch pack and Swift overlay sources for Squirrel. |
| `macos/RagImeControl/` | Native control center and diagnostics UI. |
| `macos/RagImeVoice/` | Headless native voice agent, global push-to-talk hotkey, microphone capture, and cursor insertion. It has no second control surface. |
| `macos/Shared/` | Shared Keychain and Doubao streaming-ASR protocol code used by the native apps. |
| `integrations/notion-worker/` | Signed Notion Worker webhook template and matching Custom Agent instructions. |
| `scripts/` | Build, install, health, evaluation, and foreground-verification scripts. |
| `tests/` | Unit, integration-style, contract, privacy, and patch regression tests. |
| `docs/` | Architecture, operations, acceptance criteria, status, and evaluation cases. |
| `dataset/ime_first_demo_pack.v1.json` | Isolated, deterministic input-method demonstration fixture. |
| `dataset/minimind_completion_v3_public/` | Small public-safe completion contract and semantic regression set; not a production-scale training corpus. |

## Requirements

- macOS 14 or newer for the current native build and verification path.
- Python 3.10 or newer.
- Xcode command-line tools; full Xcode is required to build patched Squirrel.
- Apple Silicon and `mlx`/`mlx-lm` for the resident local predictor.
- A separately obtained local checkpoint. Model weights are not included.
- A Volcengine application with Doubao streaming speech recognition 2.0 enabled
  is optional and required only for voice input.

The Python core intentionally has no mandatory third-party package dependency.
MLX and remote-provider support are optional runtime layers.

## Quick Start

Run the complete cross-platform test suite:

```bash
python3 -m unittest discover -s tests
```

Initialize a local database and start the sidecar:

```bash
python3 -m rag_ime.cli init-db
python3 -m rag_ime.cli sidecar-server --host 127.0.0.1 --port 8766
```

For a deterministic input-method-first demonstration, use the isolated demo
database rather than seeding personal history:

```bash
python3 scripts/ime_first_demo.py seed --reset
python3 scripts/ime_first_demo.py verify --report output/ime-first-demo-report.json
python3 scripts/ime_first_demo.py reset
```

The default `.rag-ime-demo/` route refuses `.rag-ime-data/`, performs no model
or network call during verification, and removes only rows owned by its fixed
fixture. See [the demo-data contract](docs/ime-first-demo-data.md).

Prepare and build the pinned Squirrel source with the patch pack:

```bash
scripts/prepare_squirrel_workspace.sh
scripts/build_patched_squirrel.sh build
```

Installing an input method changes user-level macOS state. Read
[`docs/runtime-and-debug.md`](docs/runtime-and-debug.md) before running the
install or restart scripts.

After a controlled installation, use the real foreground checks:

```bash
scripts/doctor_squirrel_integration.sh
scripts/verify_squirrel_foreground_trace.sh
```

Backend health or a predictor benchmark does not prove that candidates are
visible, selectable, and committed in the foreground application.

Optional voice input is installed separately so microphone/network work never
enters Squirrel's keystroke path:

```bash
scripts/build_control_center.sh install
scripts/install_voice_input_launch_agent.sh
scripts/configure_volcengine_asr.sh \
  --app-id YOUR_APP_ID \
  --access-token-file /path/to/access-token-file
launchctl kickstart -k "gui/$(id -u)/com.rag-ime.voice"
```

Credentials are restricted to the installed native binaries in macOS Keychain.
The background agent never opens an Accessibility prompt on its own; microphone
access is requested only after the user presses the voice shortcut. The Control
Center reads the agent's local status file and does not inspect or request its
own microphone/Accessibility permissions. Grant the two permissions to
`RagImeVoice` explicitly when convenient, then hold
`Option+Space` to speak and release it to finalize. See
[`docs/runtime-and-debug.md`](docs/runtime-and-debug.md#streaming-voice-input).
Optional request-level hotwords are configured only in the Control Center. The
agent sends at most 32 validated entries in the provider's `request.context`
field; disabled or empty configuration omits the field entirely. RAG-IME never
exports the Rime user dictionary for this purpose.
Remove only the voice agent with `scripts/uninstall_voice_input.sh`; pass
`--purge-credentials` to remove its Keychain entries and private hotword file as
well.

## Evaluation

The repository includes deterministic quality gates for each independent lane:

```bash
python3 -m rag_ime.cli eval-hybrid-rag-core \
  --cases-file docs/eval/hybrid_rag_core_cases.jsonl

python3 -m rag_ime.cli eval-memory-optimizer \
  docs/eval/memory_optimizer_cases.jsonl

python3 -m rag_ime.cli eval-active-rag \
  --cases-file docs/eval/active_rag_cases.jsonl
```

Hybrid RAG enforces each fixture's wall-clock latency by default; the public
gate script never disables it. `--skip-latency-check` exists only for
correctness/schema tests on uncalibrated hosted runners and must not be used as
release or performance evidence.

Use `scripts/check_product_status.py --json` for product evidence and
`scripts/check_public_release.py --allow-blocked` for the tracked-file,
license, secret-shape, foreground, and artifact-evidence release gate. The
latter exits non-zero without `--allow-blocked` while release blockers remain.
It does not treat `releaseStatus: ready` or a boolean signing claim as proof. See
[`docs/v1-foreground-acceptance.md`](docs/v1-foreground-acceptance.md) for the
foreground behavior matrix.

## Release Evidence Gate

The generated release manifest is separate from the product-status declaration.
Its schema is `rag-ime.release-manifest.v1`; a non-runnable field template lives
at [`docs/release-manifest.example.json`](docs/release-manifest.example.json).
The real manifest defaults to the ignored build path
`output/release/release-manifest.json` and must describe the exact release
commit and two hash-pinned artifact kinds: `macos_release` and
`corresponding_source`.

The gate recalculates every artifact and evidence-file SHA-256 and byte size,
rejects paths outside the repository, and requires evidence records for
codesigning, notarization, stapling, patched-Squirrel corresponding source,
third-party notices, and foreground acceptance. Each evidence record points to
a real hash-pinned file, and target-specific records repeat the exact artifact
digest so stale evidence cannot be attached to a different package. Status
booleans in `docs/product-status.json` cannot bypass a missing file or digest
mismatch.

```bash
python3 scripts/check_public_release.py \
  --manifest output/release/release-manifest.json \
  --allow-blocked
```

No real manifest or public package exists yet, so the current audit honestly
reports `release_manifest_missing` in addition to the foreground, license, and
clean-tree blockers.

An unsigned deterministic engineering staging path now exists so packaging can
be tested before those external gates:

```bash
bash scripts/build_patched_squirrel.sh
bash scripts/build_voice_input.sh
bash scripts/build_control_center.sh
python3 scripts/prepare_release_candidate.py --release-id v0.1.0-engineering
```

It creates an unsigned native-app archive, a corresponding-source archive, and
`staging-manifest.json` under the ignored `output/release-candidate/` directory.
The staging schema is intentionally different from the final release manifest,
always reports `releaseEligible: false`, and cannot satisfy the release audit.
See [release-candidate staging](docs/release-staging.md).

## Candidate Sources

Candidate provenance is a product contract, not just a UI label:

| Source | Meaning |
| --- | --- |
| `rime` | Native Rime composition candidate. |
| `model` | Local post-commit completion. |
| `rag` | Local retrieval evidence or curated phrase. |
| `memory` | Stable local memory candidate. |
| `action` | Explicit Active RAG action, such as DeepSeek generation. |
| `raw_english` | Direct code/ASCII input path. |

Rime candidates keep ownership of the composition panel. Model, RAG, and
memory candidates must not silently replace or reorder ordinary Pinyin results.

## Training and Models

The checked-in MiniMind integration uses a bare `prefix -> completion`
contract rather than a chat prompt. The local checkpoint is a project-specific
fine-tune and is not an official MiniMind release.

The public v3 seed set and gate make model work reproducible without pretending
that a tiny fixture is enough to train the final network:

```bash
python3 scripts/minimind_retraining.py audit
python3 scripts/minimind_retraining.py export \
  --output /tmp/minimind-completion-v3-pairs

# Requires an explicitly configured, already-running loopback predictor.
python3 scripts/minimind_retraining.py evaluate \
  --stage production_candidate \
  --provider env \
  --split test \
  --semantic-judgments \
    dataset/minimind_completion_v3_public/baselines/minimind-ime-v2-q8-production-20260711.judgments.json \
  --report output/minimind-quality.json
```

The set contains 19 contexts, 57 positive suffixes, 57 context-specific hard
negatives, and six continuous-Tab chains. It audits split leakage, prompt/chat
fields, prefix echo, broken word boundaries, three-candidate diversity, and
real rollout drift. A reviewed `production_candidate` run of the current Q8
checkpoint passes latency, bare-output, anti-echo, hard-negative, and
three-candidate checks, but scores semantic Top-1/Top-3 `0.0`, boundary validity
`0.833333`, and continuous Tab `0.0`. This run evaluates candidates after the
production provider's parser/filter; raw checkpoint output has a separate
`raw_model_output` contract. The reviewed raw Q8 baseline captures pre-parser
branches directly: p50 `40 ms`, p95 `150 ms`, while semantic Top-1/Top-3 and
continuous Tab remain `0.0`. See
[`docs/minimind-retraining-interface.md`](docs/minimind-retraining-interface.md).

For further training:

- Prefer consented, sanitized, real single-user typing continuations.
- Keep completions append-only and do not repeat the input prefix.
- Quarantine synthetic template corpora from the primary training mix.
- Evaluate abstention, semantic relevance, echo rate, and three-alternative
  diversity separately from inference latency.
- Keep authorized causal text, suffix-only SFT, and chosen/rejected ranking as
  separate phases. `prepare-experiment` emits a fingerprint-bound A0/A1 plan
  and refuses to mark the public regression seed as production training data.
- Onboard a finished export with `scripts/qualify_model_candidate.py prepare`.
  It creates an inactive, fingerprint-bound raw/product/continuous-Tab/latency
  evidence plan and never overwrites or activates the current model. Finalization
  still requires separately bound foreground evidence before activation can be
  reviewed.

See [`docs/personal-ime-completion-requirements.md`](docs/personal-ime-completion-requirements.md)
for the data and acceptance contract.

The optional Notion personal-knowledge lane is documented in
[`docs/notion-personal-knowledge.md`](docs/notion-personal-knowledge.md). It is
an explicit asynchronous workflow, not a passive input-method candidate source.

## Acknowledgements

This project is independent and is not endorsed by the projects below.

- [Wisdom-Weasel](https://github.com/Felix3322/Wisdom-Weasel) informed the
  prediction lifecycle and candidate-panel integration route.
- [VCPToolBox](https://github.com/lioensky/VCPToolBox) informed parts of the
  memory/RAG design study, especially persistent memory, TagMemo-style signals,
  and context injection. No VCP service is required at runtime.
- [MiniMind](https://github.com/jingyaogong/minimind) provided the small-model
  architecture and training baseline used to produce the custom local
  completion checkpoint. Upstream MiniMind weights are not redistributed here.
- [Squirrel](https://github.com/rime/squirrel) and
  [librime](https://github.com/rime/librime) provide the macOS frontend and Rime
  engine foundations.
- [MLX](https://github.com/ml-explore/mlx) and
  [MLX-LM](https://github.com/ml-explore/mlx-lm) provide the Apple Silicon
  inference runtime.
- [Ollama](https://github.com/ollama/ollama) and
  [llama.cpp](https://github.com/ggml-org/llama.cpp) are supported as optional
  local serving boundaries through the native Ollama or OpenAI-compatible
  provider contracts; neither is required for the default MLX deployment.
- [OpenLess](https://github.com/Open-Less/openless) informed the isolated voice
  coordinator, ordered PCM/WebSocket pipeline, push-to-talk lifecycle, and
  insertion fallback design. No OpenLess code or service is required at runtime.
- [LazyTyper](https://github.com/oldcai/LazyTyper-releases) informed the global
  voice-input interaction and low-friction cursor-insertion expectations. The
  referenced repository is a binary release channel; this project does not
  claim that its code is available under an open-source license.
- [Volcengine Doubao streaming ASR 2.0](https://docs.volcengine.com/docs/6561/1354869?lang=zh)
  is the optional remote speech-recognition provider for the voice lane.

All names and trademarks belong to their respective owners. Each dependency or
reference project remains governed by its own license.

## Contributing

Keep changes narrow and add tests for behavior, privacy, contracts, or patch
application. For frontend work, verify the real Squirrel foreground path rather
than relying only on preview fixtures. Do not submit personal typing history,
credentials, private model artifacts, or generated app bundles.

Before opening a pull request, run:

```bash
python3 -m compileall -q rag_ime scripts tests
python3 scripts/check_import_boundaries.py
python3 scripts/check_product_status.py --json
python3 scripts/check_public_release.py --allow-blocked
python3 scripts/evaluate_deployed_rime_lexicon.py
python3 -m unittest discover -s tests
find scripts -type f -name '*.sh' -print0 | xargs -0 -n1 bash -n
```

The public-release audit scans both tracked files and non-ignored untracked
candidate files. It blocks generated artifacts, credential-shaped strings, and
machine-specific production defaults before they can enter a clean commit.
Test fixtures and local agent notes are not treated as deployable defaults, but
they remain subject to the normal secret-shape guard unless explicitly marked
as audit fixtures. Superseded public archives are rejected entirely.

## License

This repository does not currently include a top-level project license. Public
visibility does not by itself grant permission to copy, modify, or redistribute
the project. The evidence-backed [license decision](docs/license-decision.md)
recommends GPL-3.0-only for the lowest-ambiguity single-license release and
documents a more complex Apache-2.0/GPL-3.0 split alternative. The owner still
has to approve the choice and copyright identity before `LICENSE` is created.

The old 20k template corpora, their generators, and obsolete handoff artifacts
have been removed from the working tree. The repository is still not
release-ready: the tree is dirty, strict foreground/screenshot acceptance is
incomplete, and the signed/notarized release package plus patched-Squirrel
source-compliance bundle has not been assembled. There is also no hash-verified
`output/release/release-manifest.json`; product-status flags alone cannot satisfy
the gate. `scripts/check_public_release.py` reports these conditions; it does
not delete files or choose a project license.

Third-party projects and dependencies retain their own licenses. In particular,
VCPToolBox is referenced as a design study under its CC BY-NC-SA 4.0 terms, and
MiniMind is distributed upstream under Apache License 2.0. Patched Squirrel is
derived from a GPL-3.0 project, so distributing patched Squirrel binaries or
source requires satisfying the corresponding GPL obligations. See
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) before publishing artifacts.
