# Notes

## Run prefs (persistent)

- Do not maintain the learnA study site while implementing this product repo.
- Keep production macOS input method work on the Rime/Squirrel route; the InputMethodKit app is a prototype/debug harness.

## Log

### 2026-06-30 22:53 CST
Problem:
- Squirrel side candidates could be inserted, but the first patch did not write accepted RAG choices back to the memory core.
- `max_side_candidates` could be exceeded when model and RAG candidates both filled visible slots.

Findings:
- Wisdom-Weasel's useful pattern is async prediction with request sequence invalidation, frontend-side candidate merge, and custom selection routing for appended model candidates.
- The Squirrel patch should keep librime unchanged and route side candidates by display metadata in `SquirrelInputController`.

Changes:
- Added `sourceEventId` to `displayCandidates`.
- Updated the Squirrel patch to record side candidate commits and `action-json accepted` for RAG memory candidates.
- Fixed global side-candidate cap across model and RAG candidates.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `scripts/build_macos_frontend.sh`
- `RagImeMac --preview-rime-sidecar-json`
- `git apply --check squirrel-patches/0001-add-rag-ime-sidecar.patch`

Next:
- Build and install a patched Squirrel app in a full Xcode environment.
- Replace per-request Python process spawning with a long-lived daemon or local socket.

### 2026-06-30 23:10 CST
Problem:
- Squirrel patch still spawned `python -m rag_ime.cli` on each sidecar request, which is too expensive for high-frequency typing.

Changes:
- Added `python3 -m rag_ime.cli sidecar-server` as a lightweight local HTTP sidecar.
- Added root-path HTTP aliases such as `/rime-suggest`, `/commit`, and `/action` in addition to `/api/...`.
- Updated Squirrel patch to prefer `rag_ime/sidecar_url` and fall back to CLI if the daemon is unavailable.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture sidecar-server --host 127.0.0.1 --port 18766 --no-seed`
- `swiftc -typecheck ... RagImeSidecarModels.swift RagImeSidecarClient.swift`
- `git apply --check squirrel-patches/0001-add-rag-ime-sidecar.patch`

Next:
- Full Xcode build/install of patched Squirrel remains the next hard gate.

### 2026-06-30 23:15 CST
Problem:
- Applying the Squirrel patch still required several manual commands, which is brittle when moving to a full Xcode machine.

Changes:
- Added `scripts/prepare_squirrel_workspace.sh`.
- The script clones/checks out Squirrel `2158538`, applies the patch, runs lightweight checks, and writes `rag-ime.squirrel.custom.yaml`.
- README, Squirrel patch notes, and macOS frontend notes now point to this script.

Commands:
- `bash -n scripts/prepare_squirrel_workspace.sh`
- `RAG_IME_SQUIRREL_DRY_RUN=1 scripts/prepare_squirrel_workspace.sh`
- `RAG_IME_SQUIRREL_REPO_URL=/tmp/rag-ime-research/squirrel scripts/prepare_squirrel_workspace.sh`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `scripts/build_macos_frontend.sh`

Next:
- Run the prepared checkout through full Xcode build/install and real typing.

### 2026-06-30 23:22 CST
Problem:
- After adding sidecar launchd and Squirrel prep scripts, there was no single preflight command to diagnose missing sidecar, missing patch, unprepared Squirrel checkout, or missing Xcode.

Changes:
- Added `scripts/doctor_squirrel_integration.sh`.
- Doctor reports OK/WARN/FAIL for Python, patch file, `rag_ime.cli`, Squirrel workdir, Xcode, Swift, LaunchAgent, and sidecar HTTP health.
- Docs now point users to the doctor after sidecar/Squirrel preparation.

Commands:
- `bash -n scripts/doctor_squirrel_integration.sh`
- `scripts/doctor_squirrel_integration.sh` with sidecar absent in WARN mode
- `scripts/doctor_squirrel_integration.sh` with a temporary sidecar in strict sidecar mode
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `scripts/build_macos_frontend.sh`

Next:
- Use doctor output as the preflight gate before the full Xcode Squirrel build/install.

### 2026-06-30 23:08 CST
Problem:
- A usable Squirrel integration needs the HTTP sidecar to survive login/restart, not a manually started terminal process.

Changes:
- Added user LaunchAgent install/uninstall scripts for the sidecar server.
- Added dry-run support so plist generation can be tested without loading launchd.
- Documented LaunchAgent setup in README, macOS frontend notes, and Squirrel patch pack notes.

Commands:
- `bash -n scripts/install_sidecar_launch_agent.sh`
- `RAG_IME_LAUNCH_AGENT_DRY_RUN=1 scripts/install_sidecar_launch_agent.sh`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `scripts/build_macos_frontend.sh`

Next:
- Full Xcode build/install of patched Squirrel remains the next hard gate.
