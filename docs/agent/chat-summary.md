# Chat Summary

### 2026-06-30
Topic:
- Make full Xcode setup explicit for patched Squirrel validation.

Decisions:
- Keep Squirrel/Rime as the production frontend and treat full Xcode as a first-class local prerequisite.
- Prefer external-disk Xcode download/install on this host because root disk free space is limited.

Changes:
- Added `scripts/setup_xcode_for_squirrel.sh`.
- Added `docs/xcode-squirrel-setup.md`.
- Enhanced the Squirrel doctor to show `xcode-select` and `DEVELOPER_DIR` state.

Verification:
- Local machine currently has only Command Line Tools selected.
- `xcodes` and `mas` are installed, but actual Xcode install is blocked by Apple ID/admin-password UI.

Next steps:
- Install full Xcode through Apple Developer `xcodes` or App Store UI, then run `RAG_IME_DOCTOR_REQUIRE_XCODE=1 scripts/doctor_squirrel_integration.sh`.

### 2026-06-30
Topic:
- Continue RAG-IME toward a usable Squirrel/Rime macOS input method.

Decisions:
- Keep Rime/Squirrel as the production frontend and preserve librime ownership of raw pinyin parsing.
- Treat accepted side candidates as memory feedback, not only text insertion.

Changes:
- Added side-candidate `sourceEventId` to the Rime sidecar JSON contract.
- Updated the Squirrel patch pack so accepted RAG side candidates record both a commit event and an `accepted` action.
- Fixed side-candidate cap so model and RAG candidates share the same `max_side_candidates` budget.

Verification:
- 33 Python unit tests passed.
- Fixture acceptance passed.
- macOS prototype app built successfully.
- Rime sidecar preview shows Rime candidates first and RAG side candidates with `sourceEventId`.
- Squirrel patch applies cleanly to upstream commit `2158538`.

Next steps:
- Run full Squirrel Xcode build/install/signing on a machine with Xcode.
- Convert the Python CLI sidecar into a long-lived daemon to avoid spawning a process per key update.

### 2026-06-30
Topic:
- Reduce Squirrel sidecar latency by avoiding per-request Python process startup.

Decisions:
- Reuse the existing local HTTP facade instead of creating a separate protocol.
- Squirrel should prefer `rag_ime/sidecar_url` and keep CLI fallback for fail-closed behavior.

Changes:
- Added `sidecar-server` CLI command on port `8766` by default.
- Added `/health`, `/rime-suggest`, `/commit`, `/action` root aliases in addition to `/api/...`.
- Updated the Squirrel patch pack to POST JSON to the long-running sidecar when configured.

Verification:
- 35 Python unit tests passed.
- CLI sidecar server smoke returned a valid `rag-ime.rime-sidecar.v1` response.
- Squirrel sidecar Swift files typechecked with a temporary config stub.
- Patch still applies cleanly to Squirrel `2158538`.

Next steps:
- Build/install patched Squirrel with Xcode and test real typing.

### 2026-06-30
Topic:
- Make the HTTP sidecar usable as a persistent local service.

Changes:
- Added `scripts/install_sidecar_launch_agent.sh`.
- Added `scripts/uninstall_sidecar_launch_agent.sh`.
- Added dry-run plist generation and a unit test for the LaunchAgent script.
- Documented sidecar launchd setup in README, Squirrel patch notes, and macOS frontend notes.

Verification:
- 36 Python unit tests passed.
- LaunchAgent dry-run generated a valid plist.
- Fixture acceptance passed.
- macOS prototype app still builds.

Next steps:
- Build/install patched Squirrel with Xcode and test real typing against `http://127.0.0.1:8766/api`.

### 2026-06-30
Topic:
- Make patched Squirrel checkout preparation repeatable.

Changes:
- Added `scripts/prepare_squirrel_workspace.sh`.
- Added a dry-run unit test for the prepare script.
- Updated README, Squirrel patch notes, and macOS frontend notes to use the prepare script.

Verification:
- 37 Python unit tests passed.
- Prepare script dry-run passed.
- Real prepare was tested against local Squirrel source and generated `rag-ime.squirrel.custom.yaml`.
- Fixture acceptance and macOS prototype build passed.

Next steps:
- Use `/tmp/rag-ime-squirrel` on an Xcode machine to build/install patched Squirrel and test real typing.

### 2026-06-30
Topic:
- Add a preflight check for patched Squirrel integration.

Changes:
- Added `scripts/doctor_squirrel_integration.sh`.
- Added a unit test for default WARN-mode doctor behavior.
- Documented the doctor in README, macOS frontend notes, and Squirrel patch notes.

Verification:
- Doctor WARN-mode works without a running sidecar.
- Doctor strict sidecar mode passed against a temporary `sidecar-server`.
- 38 Python unit tests passed.
- Fixture acceptance and macOS prototype build passed.

Next steps:
- Run doctor on the Xcode machine before building/installing patched Squirrel.
