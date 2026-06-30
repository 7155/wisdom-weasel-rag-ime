# Chat Summary

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
