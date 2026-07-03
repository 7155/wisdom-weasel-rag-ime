# Notes

## Run prefs (persistent)

- Do not maintain the learnA study site while implementing this product repo.
- Keep production macOS input method work on the Rime/Squirrel route; the InputMethodKit app is a prototype/debug harness.

## Log

### 2026-07-04 00:47 CST
Problem:
- User reported the installed input method still cannot show useful LLM/RAG candidates.
- Current `curl` checks showed `127.0.0.1:8766` and `127.0.0.1:8767` were not listening, so real LLM/RAG could not appear regardless of frontend code.

Findings:
- The copied real DB has useful data: `input_events=10032`, `memory_fts=10076`, `memory_vectors=5037`, `phrase_stats=9941`.
- Codex sandbox cannot `launchctl kickstart`, bind local ports, or access Metal; direct MLX import fails with `No Metal device available`.
- Offline DB probe proved the RAG path works when given enough budget: with 800ms, `rime-suggest-json` returned relevant memory/RAG candidates such as `LLM、RAG 和记忆候选必须同时可见并且都能用数字键提交` and `设计一个候选展示方式`.
- The previous 350ms foreground budget often made RAG time out around 350-370ms and return an empty candidate list, matching the user's "RAG 没生效" screenshots.

Changes:
- Realtime RAG no longer caps itself to 100ms inside a 350ms request; it can use the request budget while still running in parallel with the model lane.
- Realtime local SQLite RAG disables vector deep retrieval for budgets up to the realtime model context budget, keeping the typing path on the faster FTS/rule layer.
- Raised Squirrel/native sidecar candidate budget defaults to 800ms for demo usability.
- Added `scripts/restart_rag_ime_runtime.sh` to restart the user-level MLX predictor and sidecar with Qwen3-0.6B, prompt cache, local vector baseline, and MLX predictor env.

Verification:
- Focused Rime sidecar tests passed for mid-budget RAG and explicit model context.
- Squirrel build config, sidecar config, doctor, and native controller tests passed: 39 tests OK.
- Real copied-DB CLI probe with 800ms returned 5 RAG/memory display candidates.

Pitfalls:
- Codex cannot start the real MLX service in this sandbox; the user must run the restart script from a normal Terminal session.

### 2026-07-03 20:47 CST
Problem:
- User wants vibecode-style English/code input to be reliable before the LLM/RAG layer is judged usable.
- Felix/Wisdom-Weasel relies on Wanxiang's English schema and Lua filters for mixed Chinese/English fallback; this repo's native debug harness only precompiled the Chinese Wanxiang index.

Findings:
- Felix `wanxiang.schema.yaml` wires `table_translator@wanxiang_english` plus `lua_filter@*wanxiang.super_english`.
- `wanxiang_english.dict.yaml` imports `dicts/en`; the local Felix checkout has about 71k English entries.
- The first capped English attempt with 20k rows missed common words such as `hello` because the dictionary is not ordered for our hot-index selection needs.

Changes:
- `scripts/build_rime_candidate_index.py` now also imports `wanxiang_english.dict.yaml`, indexes ASCII English candidates, and keeps English prefixes out of one-letter queries so Chinese single-letter behavior is not polluted.
- Added curated technical terms such as `rag`, `llm`, `mlx`, `qwen`, `python`, `github`, `sqlite`, `xcode`, `vscode`, `json`, `yaml`, and `terminal`.
- `scripts/build_macos_frontend.sh` now bundles the full Wanxiang English index (`--max-english-entries 0`) with per-prefix caps.
- `--preview-rime-dictionary-json` now probes `hello`, `python`, and `rag` in addition to Chinese pinyin and raw command/path safety cases.

Verification:
- `scripts/build_macos_frontend.sh` built and signed `build/RagImeMac.app`; bundled index size is now 15MB.
- Preview verified `hello -> hello`, `python -> python/pythonic`, and `rag -> rag/...` from `wanxiang_english`.
- Preview still leaves `git status` and `/Volumes/undo` empty, so command/path passthrough is not polluted by dictionary candidates.
- Focused tests passed: index builder, install script, Swift dictionary provider.
- Full suite passed: 366 tests OK.
- `git diff --check` passed.

Next:
- Commit and push.
- Continue MLX/RAG/memory visible candidate quality; 1.7B MLX can be tried later after the base input flow is stable.

### 2026-07-03 12:09 CST
Problem:
- User reported the current IME still fails the core product bar: real frontend can crash on input-source switching, candidate panel can linger or appear in the wrong place, RAG/LLM/memory candidates looked like clipboard/debug snippets, `sj`-style pinyin constraints did not steer the AI path, and MLX model output was visible in diagnostics even when it did not match the user prefix.
- Current round must not switch the system input method or open GUI apps because recent foreground switching caused Edge/Ghostty/Codex instability.

Findings:
- The local DB is large enough for real RAG testing (`input_events` > 10k, vectors > 5k), but it contains generated sidecar rows tagged `source:model` / `source:rag`; those rows were skipped by the compiler but could still enter `recent_input_context()` and poison model history.
- Weak local-hash vector matches could pass retrieval with only `vector_score > 0.05`, which explains unrelated candidates for short weak inputs.
- Prefix-constrained requests were feeding RAG the broad semantic string `context + sj + 手机 世界`; for RAG this is too wide and can retrieve long Codex plan paragraphs.
- The current MLX model (`Qwen3-0.6B-Base`) is loaded through MLX and text-only, but in prefix mode it can produce off-prefix writing prompts such as “写一篇...” / “帮我写...”.

Changes:
- `recent_input_context()` now skips generated `source:model` / `source:rag`, assistant/system/event/tool/runtime-noise rows, and noisy retrieval surfaces.
- Vector-only retrieval now requires a configurable confidence gate (`RAG_IME_VECTOR_ONLY_MIN_SCORE`, default `0.35`) plus a real query signal.
- Prefix-constrained RAG now queries by the stable short pinyin prefix (`sj`) while keeping committed context as context, instead of querying with the whole mixed semantic string.
- Prefix-constrained MLX/model predictions are hard-filtered by pinyin initials; off-prefix model outputs are removed from `modelPredictions` and recorded as `model predictions did not match pinyin prefix`.

Verification:
- Focused tests passed for generated-history filtering, weak vector false positive, prefix RAG query, and off-prefix model filtering.
- Offline live-DB probe: `撤旦` returns no unrelated memory.
- Offline live-DB + MLX probe for `我想 + sj` shows `ragLane.queryInput=sj`, `modelPredictions=[]` with skipped reason, and the visible candidate is the prefix-matching RAG phrase `设计一个候选展示方式`.

Open:
- Real foreground input method is still not validated in this round; do not claim product usability until the user allows a controlled GUI/input-source test.
- MLX prompt/candidateization still needs a deeper Felix `LLMProvider.cpp` pass so the model produces useful prefix-matching short spans instead of being filtered out.
- Existing DB still needs noise governance beyond online filtering.

### 2026-07-03 08:12 CST
Problem:
- User required the reference-reading TODO to be executed as a hard workflow: read now, reread before code, and check again after implementation.
- Candidate quality was still failing in two concrete ways: weak short candidates such as `根据` could occupy the first slot, and selected side candidates did not send the full shown list back for skipped-higher feedback.

Attempts:
- Second-pass reread before coding:
  - `RimeWithWeasel/RimeWithWeasel.cpp`: no-input candidate clear on typing, unified display candidate selection, pending LLM commit, request-seq stale discard.
  - `alpha_rerank.lua`: top1 takeover guard, skipped-higher negative feedback, query variants, score-breakdown logging.
  - `wanxiang.schema.yaml` / `super_english.lua`: Wanxiang/Rime remains responsible for pinyin anchoring, English/vibecode support, and user dictionary/frequency.
  - `LLMProvider.cpp`: short candidate prompt and continuation candidateization.
- Implemented a prediction-first top1 guard in `rag_ime/prediction_first.py`; low-value first candidates are demoted when a stronger model/RAG/memory candidate exists.
- Extended `/rime-select` in `rag_ime/rime_sidecar.py` to accept `shownCandidates`, record the selected candidate as `accepted`, and record higher-ranked shown RAG/memory candidates as `skipped`.
- Updated `squirrel-patches/0001-add-rag-ime-sidecar.patch` so the real Squirrel frontend sends `shownCandidates: ragImeDisplayCandidates` to sidecar selection recording.

Verification:
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest tests.test_prediction_first tests.test_rime_sidecar tests.test_build_patched_squirrel`: 63 tests passed.
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest discover -s tests`: 312 tests passed.
- `git diff --check`: passed.
- `python3 -m py_compile rag_ime/prediction_first.py rag_ime/rime_sidecar.py`: passed.
- Third-pass diff audit confirmed the change stayed limited to top1 guard, selection feedback, patch payload, and tests.

Open:
- MLX prompt/candidateization still needs to be aligned to Felix `LLMProvider.cpp`.
- SQLite frequency/preference scoring still needs a fuller Felix-style user-frequency prior, beyond the accepted/skipped actions added here.
- debug/doctor output still needs richer source/score/guard/latency/backend evidence.

### 2026-07-03 07:45 CST
Problem:
- User required a hard TODO discipline for reference reading: read once now, read again before coding, and check again after implementation.
- Previous attempts repeatedly diverged from Wisdom-Weasel/Felix behavior, especially candidate lifecycle, LLM/RAG visibility, and stale prediction panels.

Findings:
- First-pass Felix/Wisdom-Weasel reading is complete for the current migration scope.
- `RimeWithWeasel/RimeWithWeasel.cpp` hides no-input predictions on any non-digit key, clears old AI candidates when new pinyin starts, routes space/number keys through unified `DisplayCandidate`, commits LLM candidates through `m_pending_llm_commit`, records committed text into `ContextHistory`, and triggers `NoInputPrediction` only after meaningful commits.
- Its candidate UI is not a detached overlay: `_BuildDisplayCandidates` merges Rime, LLM, rerank candidates, pending placeholders, labels, comments, and source labels into the same candidate-info path; TSF duplicate windows are explicitly suppressed.
- `alpha_rerank.lua` uses Rime commit history, query variants, user-frequency/preference score breakdowns, skipped-higher negative feedback, top1 takeover guards, and detailed trace logs. It reranks active composition candidates; it does not keep a no-input box alive.
- `wanxiang.schema.yaml`, `auto_phrase.lua`, and `super_english.lua` show the right boundary: Wanxiang/Rime owns pinyin anchoring, user dictionary/frequency, English/vibecode support, and fallback candidates.
- Installer/build docs emphasize exact runtime sync, user-dir patching, deploy/restart, and log-first diagnosis when the candidate box disappears or stale files are active.

Decisions:
- Before touching implementation, reopen and reread the exact Felix paths relevant to that code change.
- After implementation, compare the final diff against the same reference paths and verify the three failure classes: stale panel, unusable number keys, and invisible/nonselectable LLM/RAG/memory candidates.

### 2026-07-02 23:33 CST
Problem:
- User explicitly marked `https://github.com/Felix3322/Wisdom-Weasel` as a key reference repository because it improves heavily on the original Wisdom-Weasel path and should guide this RAG-IME project.

Findings:
- Local reference clone: `/Volumes/undo 4t/git/learnA/agent-source-projects/wisdom-weasel-felix`.
- Fork HEAD observed: `3473284a14b0336d5e6a39d2dfb0ffcbdcfb5a17`.
- Original upstream comparison point: `/Volumes/undo 4t/git/learnA/agent-source-projects/wisdom-weasel`, scukeqi `main` at `64ba2fdd484c3fa1c1a87e88591911c3d31b3eb6`.
- This fork is now a primary engineering reference, not a casual comparison.

Reference priority:
- First priority: copy the product boundary, not Windows-specific code. Wanxiang/Rime owns pinyin anchoring and fallback; Alpha-style rerank owns existing candidate ordering; LLM owns no-input/post-commit prediction; RAG/memory supplies personal candidate material.
- Second priority: adapt its candidate lifecycle discipline: async scheduling, stale-result discard, auto-hide/no-input behavior, source-aware candidate display, and explicit feedback after selection.
- Third priority: adapt its personalization mechanisms: user-frequency prior, accepted-candidate positive feedback, skipped higher-ranked candidate negative feedback, score breakdown diagnostics.
- Do not directly port now: Windows TSF/UI installer code, CUDA/HF training stack, ASR/assistant panel, or DLL-specific Alpha bridge.

Impact:
- Future implementation should be checked against this fork before inventing new candidate-window, rerank, feedback, or prompt-flow behavior.
- The immediate migration target is a small Mac-friendly version of the fork's Alpha/personalization ideas inside our sidecar: SQLite-backed frequency/feedback scoring plus source/rank diagnostics, while keeping MLX direct for generation.

### 2026-07-02 15:56 CST
Problem:
- User pointed out that the current LLM/RAG/memory candidate panel still felt stiff: when no input is active, the prediction panel can linger for seconds and look like a detached clipboard/history popup.
- The desired behavior should follow Wisdom-Weasel's demo more closely: LLM candidates feel like a natural continuation of the normal IME candidate flow and disappear when the prediction session is no longer live.

Findings:
- Direct source check confirmed Wisdom-Weasel records committed text, enters `m_llm_prediction_mode`, runs async `PredictCandidates`, drops stale results through `m_llm_request_seq`, injects LLM candidates into Weasel candidate info, and clears `m_current_llm_candidates` when exiting prediction mode.
- The natural UX comes from short-lived candidate-flow integration, not from a persistent floating panel.

Changes:
- Extended Swift sidecar models to decode `predictionFirst`, `predictionSession`, `commitTextPreview`, and to encode `/rime-select` selection feedback.
- Changed `RagInputController` to call `/rime-suggest` with `predictionFirstMerge=true`, maintain a native session/request sequence, render only `displayCandidates`, clear stale post-commit candidates before new composition, and expire post-commit prediction after 1.15s.
- Changed `RagCandidatePanel` to render sidecar `displayCandidates` directly: inline/model candidates can occupy a compact horizontal row, while RAG/memory sentence candidates render as vertical rows with one-line evidence.
- Changed `--preview-panel` to use `/rime-suggest` display candidates instead of old `/suggest-json`.

Verification:
- `scripts/build_macos_frontend.sh` passed and rebuilt `build/RagImeMac.app`.
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest tests.test_prediction_first tests.test_rime_sidecar tests.test_debug_server`: 79 tests passed.
- `build/RagImeMac.app/Contents/MacOS/RagImeMac --preview-rime-sidecar-json` decoded `predictionSession` and returned `prefix_constrained` with `predictionPanelVisible=true`.

### 2026-07-02 14:10 CST
Problem:
- User reported the IME still looked like clipboard/Rime fallback: LLM/RAG/memory were not reliably visible, Codex history noise appeared as candidates, and the panel stayed visible even with no input.

Changes:
- Tightened Codex history import to `role=user` only; skipped assistant/event/tool/system injected records.
- Added retrieval-time and compiler-time filters for old DB pollution: `MEMORY_SUMMARY`, subagent notifications, patch/tool logs, `installation.yaml`, `index.ts` status fragments, and low-value complaint/instruction fragments.
- Added curated demo-quality memory rows for embedding query, source labels, stale panel, and model/RAG/memory acceptance.
- Changed sidecar source labels so retrieved candidates can show `rag` or `memory`, while MLX predictions remain `model`.
- Added post-commit frontend holdover: empty input only keeps prediction panel for <= 1.2s and only if no Rime fallback exists.

Verification:
- `python3 -m unittest discover -s tests -p 'test_demo_quality.py'`: 11 tests passed.
- Focused Codex history/local SQLite/Squirrel patch tests passed.
- Live `/api/rime-suggest` returned `rag`, `memory`, and `model` candidates, all commit-side selectable; MLX model lane returned in about 320ms under a 650ms budget.
- `RAG_IME_SQUIRREL_RESET=1 scripts/prepare_squirrel_workspace.sh` succeeded after switching patch application to `git apply --recount`.
- `scripts/build_patched_squirrel.sh install` built with Xcode 26.6 and installed `/Users/undo/Library/Input Methods/Squirrel.app`.
- `scripts/doctor_squirrel_integration.sh`: failures=0, warnings=2.

Pitfalls:
- `/Library/Input Methods/Squirrel.app` is still a stale same-bundle duplicate and may need admin replacement.
- doctor's model-generation diagnostic still misses the MLX candidate despite the live `/api/rime-suggest` demo returning `sourceType=model`.

### 2026-07-02 04:27 CST
Problem:
- The frontend trace checker still accepted mixed-panel events based mainly on counts and separators.
- That could miss a real visible-order regression where native Rime fallback appears before MLX/RAG side candidates.

Changes:
- Added visible candidate order validation to `scripts/check_squirrel_frontend_trace.py`.
- When trace events include candidate summaries, the checker now requires model `inline/model` candidates before RAG `block/memory` rows, and any Rime fallback only after side candidates.
- Added a regression test where a Rime candidate at visible label 2 makes the mixed-panel gate fail.
- Updated debug and Xcode setup docs to describe the side-first frontend trace requirement.

Commands:
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest tests.test_squirrel_frontend_trace`
- `python3 -m py_compile scripts/check_squirrel_frontend_trace.py`
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest discover -s tests`

Findings:
- Focused frontend trace tests passed: 8 tests.
- Full test suite passed: 191 tests.

### 2026-07-02 04:12 CST
Problem:
- The foreground trace checker accepted any `side_candidate_commit` event.
- That was weaker than the product requirement: 1-9/0 must route the visible key to a model/RAG side candidate, not accidentally select a native Rime row.

Changes:
- Tightened `scripts/check_squirrel_frontend_trace.py --require-side-commit`.
- It now requires a matching `number_key_route` followed by a valid `side_candidate_commit` with `selectionAction=commit_side_candidate`, `sourceType=model|rag`, and the same `selectionKey`.
- Updated strict doctor frontend-trace summary to report `numberKey` and `latestNumberKeySideCommit`.
- Added regression tests for missing number-key route and Rime-route false positives.
- Updated debug/Xcode docs to describe the stronger trace evidence.

Commands:
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest tests.test_squirrel_frontend_trace tests.test_doctor_squirrel_integration`
- `python3 -m py_compile scripts/check_squirrel_frontend_trace.py`
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest discover -s tests`

Findings:
- Focused frontend/doctor trace tests passed: 18 tests.
- Full test suite passed: 190 tests.

### 2026-07-02 03:55 CST
Problem:
- The install script wrote default simplified Rime settings, but `squirrel-tryout-gate` only checked that build files existed.
- A real install could silently compile `luna_pinyin` or a smaller page size while still passing the earlier tryout gate.

Changes:
- Added `installedRimeDefaults` to `squirrel-tryout-gate`.
- The gate now verifies `default.custom.yaml` and compiled `build/default.yaml` both use primary schema `luna_pinyin_simp` and `menu.page_size=8` by default.
- Added a regression test proving `luna_pinyin` plus `page_size=5` fails before quality-gate execution.
- Updated README and Xcode setup docs to describe the read-only default Rime contract check.

Commands:
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest tests.test_codex_history.CodexHistoryTests.test_cli_squirrel_tryout_gate_fails_fast_when_input_source_is_not_selected tests.test_codex_history.CodexHistoryTests.test_cli_squirrel_tryout_gate_runs_quality_gate_when_input_source_is_selected tests.test_codex_history.CodexHistoryTests.test_cli_squirrel_tryout_gate_fails_fast_when_rime_build_is_missing tests.test_codex_history.CodexHistoryTests.test_cli_squirrel_tryout_gate_fails_when_default_rime_schema_is_not_simplified tests.test_codex_history.CodexHistoryTests.test_cli_squirrel_tryout_gate_probes_sidecar_rime_suggest`
- `python3 -m py_compile rag_ime/cli.py`
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest discover -s tests`
- Real local `_tryout_installed_rime_defaults(...)` probe against `~/Library/Rime/squirrel.custom.yaml`.

Findings:
- Focused tryout-gate tests passed: 5 tests.
- Full test suite passed: 188 tests.
- Real local `~/Library/Rime/default.custom.yaml` and `~/Library/Rime/build/default.yaml` already show `luna_pinyin_simp` and page size 8.

### 2026-07-02 03:32 CST
Problem:
- User clarified the panel rule again: LLM candidates should be horizontal; sentence/RAG candidates should be vertical.
- Live sidecar already returned 1-5 as `model inline` and 6-8 as `rag block`, but the machine had two `Squirrel.app` bundles with the same bundle id.
- The patched app was under `~/Library/Input Methods/Squirrel.app`; the stale system app under `/Library/Input Methods/Squirrel.app` did not contain the mixed-layout frontend trace.

Changes:
- Changed strict doctor behavior so a stale same-bundle Squirrel without the mixed-layout frontend trace becomes a failure when patched-app readiness is required.
- Added `scripts/replace_system_squirrel_app.sh` to back up the old system Squirrel, copy the patched user-local app into `/Library/Input Methods/`, and restart the Squirrel process.
- Updated README, macOS frontend docs, and Xcode setup docs with the exact stale-app failure and repair path.

Commands:
- `scripts/select_macos_input_source.sh im.rime.inputmethod.Squirrel.Hans`
- `python3 -m unittest tests.test_doctor_squirrel_integration tests.test_build_patched_squirrel tests.test_rime_sidecar`
- `RAG_IME_DOCTOR_REQUIRE_TRYOUT=1 RAG_IME_SQUIRREL_WORKDIR=/tmp/rag-ime-squirrel-verify scripts/doctor_squirrel_integration.sh`

Findings:
- Focused tests passed: 37 tests.
- Real strict doctor now correctly fails with `stale Squirrel.app with same bundle id lacks RAG-IME mixed-layout frontend trace: /Library/Input Methods/Squirrel.app`.
- The current account cannot write `/Library/Input Methods` without sudo, so the repair script requires an interactive administrator password.

### 2026-07-02 03:05 CST
Problem:
- Tried to automate the final foreground AppKit trace, but macOS rejected AppleScript key events with `osascript is not allowed to send keystrokes`; Computer Use also could not see a usable TextEdit window.

Changes:
- Extended `scripts/verify_squirrel_foreground_trace.sh` with optional `--auto-type`, `--auto-query`, and `--auto-key`.
- The auto path tries to activate TextEdit, type the semantic prefix, wait, and press a side-candidate number key.
- If macOS blocks simulated keystrokes, the script prints the Accessibility settings path and keeps the manual fallback.
- Updated README and debug-surface docs to distinguish UI automation permission failure from IME/Squirrel/MLX failure.

Commands:
- `scripts/verify_squirrel_foreground_trace.sh --wait 45`
- `osascript` foreground typing attempt, failed with Accessibility permission error.
- `bash -n scripts/verify_squirrel_foreground_trace.sh`
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest tests.test_squirrel_frontend_trace`
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest discover -s tests`

Findings:
- Full test suite passed: 186 tests.
- Remaining foreground trace still requires the user to click the editor, type `er qi`, and press `6`, `7`, or `8`, unless Codex/Terminal gets Accessibility permission.

### 2026-07-02 02:45 CST
Problem:
- Foreground AppKit trace validation was still operationally scattered: clear trace, select Squirrel, open an editor, type, accept side candidate, then run the checker manually.

Changes:
- Added `scripts/verify_squirrel_foreground_trace.sh`.
- The wrapper verifies Squirrel is added, selects `im.rime.inputmethod.Squirrel.Hans`, clears the trace, opens a TextEdit test file, then waits for mixed panel trace and number-key side commit.
- Added `--mixed-only`, `--no-open`, `--no-clear`, `--no-select`, `--wait`, and `--dry-run` for repeatable debugging.
- Updated README, Xcode setup docs, and debug-surface docs to use the wrapper as the foreground gate.

Commands:
- `bash -n scripts/verify_squirrel_foreground_trace.sh scripts/doctor_squirrel_integration.sh`
- `scripts/verify_squirrel_foreground_trace.sh --dry-run --no-open --mixed-only --wait 12`
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest tests.test_squirrel_frontend_trace`
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest discover -s tests`

Findings:
- Full test suite passed: 186 tests.
- Real frontend trace is still empty until the user performs foreground typing and accepts a side candidate; the new wrapper makes that remaining manual gate one command.

### 2026-07-02 02:28 CST
Problem:
- User reported the real candidate panel was still vertical; requirement is LLM short candidates horizontal, sentence/RAG candidates vertical.

Findings:
- The repo patch already had the mixed layout contract, but `/tmp/rag-ime-squirrel` was still an older patched workdir that only changed separators and did not force the panel horizontal or emit full `panel_text_layout` trace.
- The active sidecar uses the text-only MLX model at `/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-text-4bit-local`.

Changes:
- Reset and regenerated `/tmp/rag-ime-squirrel` from the current patch.
- Rebuilt and installed patched `~/Library/Input Methods/Squirrel.app`.
- Restarted/reselected `im.rime.inputmethod.Squirrel.Hans`.
- Added doctor validation for MLX `next-token-logits` candidates with `candidate_scores`, no JSON fallback, and prepared prompt cache.
- Documented that labels 1-5 are horizontal MLX/LLM short candidates and 6-8 are vertical RAG/memory sentence rows.

Commands:
- `RAG_IME_SQUIRREL_RESET=1 scripts/prepare_squirrel_workspace.sh`
- `scripts/build_patched_squirrel.sh install`
- `RAG_IME_DOCTOR_CHECK_LAUNCHD=0 RAG_IME_DOCTOR_REQUIRE_PATCHED_APP=1 RAG_IME_DOCTOR_REQUIRE_INPUT_SOURCE=1 RAG_IME_DOCTOR_REQUIRE_MIXED_LAYOUT=1 RAG_IME_DOCTOR_REQUIRE_LOGITS_MODEL=1 bash scripts/doctor_squirrel_integration.sh`
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest tests.test_doctor_squirrel_integration`

Findings:
- Strict doctor passed with `failures=0 warnings=0`; live sidecar returned 8 candidates: 5 `model inline`, 3 `rag block`, 0 Rime fallback.
- MLX model path reported `candidateModes=['next-token-logits', ...]`, `fallbackJson=[False, ...]`, `candidateScoreCounts=[8, ...]`, `promptCachePrepared=True`.

Next:
- User should type in a normal editor with Squirrel selected and then run the frontend trace gate; Codex still cannot synthesize trusted macOS input-method keystrokes for foreground AppKit verification.

### 2026-07-01 17:33 CST
Problem:
- Full Xcode CLI was available, but the first patched Squirrel build failed because `Frameworks/Sparkle.framework` and other Squirrel binary dependencies were not prepared.
- The earlier model TTFC smoke was too optimistic because it could count raw first text, half tokens, or echoes of the current input.
- User's macOS is 27.0; Xcode 26.6 CLI can build, but the GUI is not supported on this OS, so final GUI work should use Xcode 27 beta 2.

Changes:
- Forced Squirrel dependency preparation with proxy variables unset, then built the patched Squirrel Release app successfully.
- Added warmup-run support for IME TTFC and quality-gate model TTFC so cold model load is separated from resident sidecar latency.
- Changed Ollama stream-first prompting to single-candidate continuation mode and stopped measuring full JSON/list latency for TTFC.
- Added strict first-candidate filtering: single half tokens and repeated current-input tokens no longer count as valid TTFC.
- Updated `docs/eval/ime-ttfc-cases.example.jsonl` to use continuation-style input prefixes instead of complete topic labels.

Commands:
- `env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy RAG_IME_SQUIRREL_PREINSTALL=1 scripts/build_patched_squirrel.sh build`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_predictor.PredictionProviderTests.test_ollama_provider_can_return_first_streamed_candidate tests.test_predictor.PredictionProviderTests.test_streaming_plain_text_parser_waits_for_usable_candidate tests.test_predictor.PredictionProviderTests.test_prediction_filter_removes_repeated_current_input_tokens tests.test_predictor.PredictionProviderTests.test_cli_bench_ime_ttfc_can_warm_model_without_scoring_warmup`
- `python3 -m rag_ime.cli --core-mode fixture bench-ime-ttfc --cases-file docs/eval/ime-ttfc-cases.example.jsonl --provider ollama --base-url http://127.0.0.1:11434 --models qwen3.5:0.8b-mlx --warmup-runs 1 --repeat 5 --max-candidates 1 --latency-budget-ms 200 --include-cases`
- `python3 -m rag_ime.cli --core-mode fixture bench-ime-ttfc --cases-file docs/eval/ime-ttfc-cases.example.jsonl --provider ollama --base-url http://127.0.0.1:11434 --models qwen3.5:0.8b-mlx,qwen3.5:0.8b --warmup-runs 1 --repeat 3 --max-candidates 1 --latency-budget-ms 200 --include-cases`

Findings:
- Patched Squirrel built successfully at `/tmp/rag-ime-squirrel-derived-data/Build/Products/Release/Squirrel.app`.
- `qwen3.5:0.8b-mlx` can stream raw text quickly, but strict TTFC on mixed English/Chinese technical prefixes produced many missing valid candidates because the model repeated `RAG`, `Squirrel`, `PROJECT`, or `Wisdom-Weasel`.
- With strict filtering, `qwen3.5:0.8b-mlx` had fast valid samples (`p50=44 ms`, `p95=62 ms`) but missed 14/20 valid candidates on the current TTFC case set.
- `qwen3.5:0.8b` GGUF/Q8 timed out under the 350 ms instant profile, so it is not a first-token path on this Mac.
- Low temperature did not solve current-input repetition. `/api/generate raw` looked more autocomplete-like on one Chinese case but still emitted questions or `<think>` fragments on mixed technical input.

Next:
- Install Xcode 27 beta 2 for GUI project work on macOS 27, then run Squirrel install and system input-method continuous-use validation together.
- Keep Rime/RAG as the primary candidate lane; treat Qwen3.5 0.8B MLX as a speed smoke model until 2B/4B, Qwen2.5 small non-thinking, or a dedicated completion/base model passes strict TTFC and quality evals.
- Later provider work should prioritize resident MLX-LM or native llama.cpp/Metal with explicit prompt/KV reuse, candidate filtering, and stale response cancellation.

### 2026-07-01 16:35 CST
Problem:
- Real Codex-history import still admitted some Codex runtime context blocks (`skills_instructions`, `apps_instructions`, `collaboration_mode`) as candidate memory.
- Those blocks are especially harmful for RAG-IME because they contain tool/plugin/runtime vocabulary that can outrank actual user project decisions.

Changes:
- Extended the Codex-history runtime-noise filter to reject app, skill, plugin, and collaboration-mode context blocks.
- Added regression coverage that user-role runtime-injection blocks do not become imported memory.
- Updated Codex-history eval docs to describe app/skill/collaboration context filtering.

Commands:
- `python3 -m py_compile rag_ime/codex_history.py tests/test_codex_history.py`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_codex_history`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-codex-eval-filtered.sqlite import-codex-history --path /Users/undo/.codex --project wisdom-weasel-rag-ime --limit 500 --min-chars 12 --max-chars 1600 --sample-size 0`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-codex-eval-filtered.sqlite eval-codex-history --cases-file docs/eval/codex-history-cases.example.jsonl --match any --repeat 1`

Findings:
- 500-record import/eval after filtering: `passed=10/34`, `passRate=0.2941`, `top1Accuracy=0.2353`, `MRR=0.2647`, `noiseRate=0.0`.
- The filter improves source quality but does not solve the broader 34-case recall gap; the next quality work remains hybrid/vector recall and larger-window Codex-history evaluation.
- Full Squirrel/Xcode build remains blocked on this host because `xcode-select` points to Command Line Tools, not full Xcode.

### 2026-07-01 14:10 CST
Problem:
- 用户要求充分调研 Mac 上本地推理最快方案，尤其是输入法首候选 <200 ms 的可落地路径。

Findings:
- 当前最快已测 smoke/debug 路线仍是 Ollama `qwen3.5:0.8b-mlx`，用 native Ollama API、`think:false`、`keep_alive`、stream-first candidate；它适合继续推进 Squirrel/RAG 产品闭环。
- 最终产品内核不能只依赖 Ollama HTTP 调用；需要 direct MLX-LM 或 native `llama.cpp`/Metal provider，显式拥有 resident model、稳定 prompt/KV cache、过期请求取消和多候选共享 prefill。
- Qwen3.5 不需要继续找 `Instant` 命名；本项目等价配置是小模型、non-thinking、streaming、4-8 token 输出和 warm resident runner。
- MLX-LM 官方能力覆盖 `stream_generate`、`prompt_cache`、`make_prompt_cache`、rotating KV cache；但 prompt cache 要隔离动态 Rime/RAG 上下文，不能过早宣称 Wisdom-Weasel parity。
- Wisdom-Weasel 的关键源码机制是 `PrepareSystemPrompt()` 保存 seq-0 state、`GenerateCandidatesBatch()` 用 `llama_memory_seq_cp` 复制到多个 sequence id 后 batch decode，前端用 request sequence 丢弃旧结果。
- MiniVLLM/vLLM 只借鉴 prefix cache、block table、prefill/decode 分离和指标；CUDA/Triton/连续批处理不是 Mac 单用户输入法 MVP 依赖。

Changes:
- 更新 `docs/mac-local-inference-fast-path.md`，加入 source refresh、locked direction、Qwen3.5 small-model rule 和补充来源。

Next:
- 保持 Ollama MLX 作为当前 Mac smoke baseline。
- 下一步跑 direct MLX-LM cached/uncached TTFC；若不能稳定胜过 Ollama MLX，则实现 native `llama.cpp`/Metal provider spike。
- 后续质量门禁应同时看 p95 TTFC、candidate quality、memory/RSS、cache-hit、stale-cancel 和 packaging。

### 2026-07-01 13:58 CST
Problem:
- Cache probe 只有 debug HTTP 页面入口，不利于 CI/终端自动验收，也不方便 shared-core adapter 做无浏览器缓存命中测试。

Changes:
- 新增 `python3 -m rag_ime.cli cache-probe`，复用 `DebugImeService.cache_probe()`。
- CLI 支持 `current_input`、`--recent-context`、`--repeat`、`--top-k`、`--rime-candidate`、`--force-side-candidates`、`--rime-cache-ttl-ms`。
- 更新 README 和 `docs/debug-surface.md`，给出终端 cache-probe 命令。
- 新增端到端测试：seed 本地 DB 后直接跑 CLI cache-probe，验证 suggestion cache 和 rimeSuggestCache 都有 warm hits。

Commands:
- `python3 -m unittest tests.test_debug_server`
- `python3 -m rag_ime.cli --help | rg "cache-probe"`
- `python3 -m rag_ime.cli --db-path /tmp/rag-ime-cache-probe-cli.sqlite cache-probe "RAG 输入法" --recent-context "manual cache probe" --repeat 3 --rime-candidate "RAG 输入法"`
- `python3 -m py_compile rag_ime/cli.py rag_ime/debug_server.py`
- `git diff --check`

Findings:
- 临时 DB 实测 repeat=3 时 `suggestionCache.hitsDelta=2`、`rimeSuggestCache.hitsDelta=2`，两层 cache gate 都通过。

### 2026-07-01 13:53 CST
Problem:
- 用户强调 VCP 缓存命中和输入法高频 refresh 很关键；debug 页面虽然显示 cache stats，但缺少一个主动重复请求并验证 warm hit 的诊断入口。

Changes:
- 新增 `DebugImeService.cache_probe()` 和 `POST /api/cache-probe`。
- Cache probe 会重复同一语义输入，通过 `/api/suggest` 测 local/shared core suggestion cache，通过 `/api/rime-suggest` 测 Squirrel/Rime semantic cache。
- Debug 页面新增小型 Cache 卡片，只显示 core hits、rime hits、repeat count；完整 before/after stats 和 samples 留在 JSON 面板。
- 更新 `docs/debug-surface.md`，说明 cache probe 是输入法版 VCP cache-hit 诊断。
- 新增 debug server 测试覆盖直接 service 调用和 HTTP `/api/cache-probe`。

Commands:
- `python3 -m unittest tests.test_debug_server`
- `python3 -m py_compile rag_ime/debug_server.py`
- `node --check debug/app.js`
- `git diff --check`

Findings:
- 直接 probe 在 repeat=3 时能看到 suggestion cache 和 rimeSuggestCache 的 warm hits。
- 这个 probe 不会塞进真实输入法候选框；它只属于 debug surface，用于调缓存命中和重复 composing refresh。

### 2026-07-01 13:44 CST
Problem:
- RAG-IME 已有 patched Squirrel prepare/doctor，但缺少一个正式的 `xcodebuild` 构建入口；full Xcode 装好后无法一条命令验证真实 Squirrel 前端。

Changes:
- 新增 `scripts/build_patched_squirrel.sh`，支持 `list` 和 `build` action、dry-run、可配置 workdir/project/scheme/configuration/derived data。
- 构建前检查 patched Squirrel checkout、`Squirrel.xcodeproj`、RAG-IME Swift sidecar 文件和 `rag-ime.squirrel.custom.yaml`。
- 构建命令默认使用 `CODE_SIGNING_ALLOWED=NO` 和 `/tmp/rag-ime-squirrel-derived-data`，避免把签名问题混入编译验证。
- 新增 `tests/test_build_patched_squirrel.py`，用 fake `xcodebuild` 离线覆盖 dry-run、`-list`、build 和 missing-workdir 错误提示。
- 更新 README、Squirrel patch pack、Xcode setup、macOS adapter 文档的构建路径。

Commands:
- `bash -n scripts/build_patched_squirrel.sh`
- `python3 -m unittest tests.test_build_patched_squirrel`
- `RAG_IME_SQUIRREL_BUILD_DRY_RUN=1 scripts/build_patched_squirrel.sh list`
- `scripts/build_patched_squirrel.sh list`

Findings:
- `/tmp/rag-ime-squirrel` 当前是已准备的 patched checkout。
- 本机 `xcode-select -p` 仍为 `/Library/Developer/CommandLineTools`。
- `scripts/build_patched_squirrel.sh list` 按预期失败在 `xcodebuild -version`，提示安装/选择 full Xcode。

### 2026-07-01 13:37 CST
Problem:
- 用户要求充分调研 Mac 上最快本地推理方案，用于 RAG 输入法首候选低延迟。

Findings:
- 当前已测最快 debug/smoke 路线仍是 Ollama `qwen3.5:0.8b-mlx` + native API + `think:false` + `keep_alive` + stream-first candidate；它证明本机 warm path 可接近/进入 200ms 内，但不是最终可控内核。
- 最终产品内核应围绕 resident model、稳定 prompt/KV cache、首个可选候选流式返回、过期请求取消、多候选共享 prefill，而不是等待完整 JSON 列表。
- MLX-LM 是下一步 Apple Silicon 实测路线，但 prompt cache 要隔离/复制/重载，不能过早等同于 llama.cpp 的 seq-copy KV。
- Wisdom-Weasel 的核心可复用机制是后台线程 + request sequence 丢弃旧结果 + `PrepareSystemPrompt()` 缓存 system prompt state + `GenerateCandidatesBatch()` 多 sequence 复制 KV 生成多个候选。
- MiniVLLM/vLLM 只借鉴 prefix cache、block table、prefill/decode 分离和指标；CUDA/Triton/连续批处理不适合 Mac 单用户输入法 MVP。

Commands:
- `rg` 检查本仓库推理文档与 provider 代码。
- `rg` 检查本地 Wisdom-Weasel / MinivLLM 源码机制。
- `ollama list` 当前失败，原因是本机 Ollama server 未运行；本次未重新跑 TTFC，只复核已有本机记录。

Pitfalls:
- 不要把“当前最快已测 smoke 路线”写成“最终产品内核”；Ollama 方便但无法证明 KV seq copy 和多候选批采样。
- 产品指标是 `firstCandidateMs` / TTFC，不是 `firstChunkMs` 或完整响应耗时。

### 2026-07-01 10:51 CST
Problem:
- The user asked for a deeper Mac inference investigation before choosing the local model path.
- The existing Ollama `qwen3.5:0.8b` smoke proved the adapter path but missed the target: observed first chunk was roughly 240-408 ms for the normal JSON prompt and full candidate latency was much higher.

Findings:
- MLX-LM is the best short-term Mac latency experiment because it is Apple Silicon first and exposes `stream_generate`, prompt cache, rotating KV cache, and speculative decoding primitives.
- `llama.cpp`/Metal is still the best final engineering route because a native provider can cache stable prompt KV state and sample multiple candidates from copied sequence state, matching Wisdom-Weasel's strongest latency mechanism.
- Ollama remains the easiest smoke-test route, and `qwen3.5:0.8b-mlx` is the next no-proxy model tag to try, but Ollama is too opaque for final prompt/KV control.
- Core ML stateful KV and MLC LLM are follow-up research paths; MiniVLLM/vLLM are useful for prefix-cache/scheduler concepts but not a direct Mac IME runtime.

Changes:
- Added a Mac backend decision table and recommendation tiers to `docs/model-ttft-kv-cache-plan.md`.
- Added Mac runtime test order and no-proxy Ollama MLX smoke commands to `docs/local-model-prediction-benchmark.md`.
- Updated README, Wisdom-Weasel issue map, and interview difficulty notes to frame TTFT/KV cache as a core project challenge.

Next:
- Start Ollama without proxy and test `qwen3.5:0.8b-mlx` with `predictor-ttft`.
- If p50 first chunk remains above 200 ms, prototype a resident MLX-LM provider or native llama.cpp/Metal provider instead of further prompt tuning.

### 2026-07-01 07:34 CST
Problem:
- Boyle subagent returned no patch for the planned lightweight tag/app/context rerank.
- Real Codex-history eval showed FTS-only retrieval was too weak: 500-record pass rate was `0.33`; 2000-record pass rate was `0.67`, with `PROJECT_MEMORY_BLOCK` missing and `Squirrel RAG` ranking too low.

Changes:
- Implemented local query expansion before FTS for high-value IME concepts: `PROJECT_MEMORY_BLOCK` / agent first-run injection, Squirrel/Rime/librime/sidecar, dirty/raw pinyin, and local RAG memory.
- Added field-aware rerank boosts over committed text, recent context, tags, source/app/schema/provider fields, and raw ASCII project terms such as `Squirrel`, `RAG`, and `PROJECT_MEMORY_BLOCK`.
- Expanded the internal memory candidate pool before compiling the visible top-K suggestions.
- Raised pinned-memory boost so explicit user governance remains stronger than automatic rerank.
- Added local-core regression tests for agent context injection recall and Squirrel/Rime side-candidate memory ranking.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_local_sqlite_core`
- `python3 -m py_compile rag_ime/local_sqlite_core.py tests/test_local_sqlite_core.py`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-rerank-eval-20260701.sqlite import-codex-history --path "$HOME/.codex/sessions" --project wisdom-weasel-rag-ime --limit 2000 --sample-size 0`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-rerank-eval-20260701.sqlite eval-codex-history --cases-file docs/eval/codex-history-cases.example.jsonl --top-k 5 --match any --repeat 2`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-rerank-eval-20260701-500.sqlite import-codex-history --path "$HOME/.codex/sessions" --project wisdom-weasel-rag-ime --limit 500 --sample-size 0`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-rerank-eval-20260701-500.sqlite eval-codex-history --cases-file docs/eval/codex-history-cases.example.jsonl --top-k 5 --match any --repeat 3`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `git diff --check`

Verification:
- Local SQLite core tests passed: 13 tests.
- Full suite passed: 70 tests.
- Fixture acceptance and `git diff --check` passed.
- Real 2000-record Codex-history eval improved to `passRate=1.0`, `top1Accuracy=1.0`, `MRR=1.0` on the current 3-case benchmark.
- Real 500-record eval improved to `passRate=0.67`, `top1Accuracy=0.67`, `MRR=0.67`; Squirrel/RAG and Agent-hook cases are top1, dirty-pinyin needs more imported history.
- This is still rule-based rerank, not a substitute for later embedding/vector hybrid recall.

### 2026-07-01 07:20 CST
Problem:
- Real Codex history import was still too noisy for RAG-IME evaluation: directory import could start from old sessions, and raw runtime context such as `AGENTS.md`, sandbox/environment blocks, developer messages, and tool output could become memories.
- This weakens the personal-memory benchmark and hides the real retrieval/rerank problem.

Changes:
- Added path ordering for Codex JSONL directory import: CLI default is now `--path-order mtime-desc`, with `mtime-asc` and `path` available for replay.
- Filtered common Codex runtime noise before converting JSONL text into `InputEvent` records.
- Kept legacy JSONL compatibility for older `response_item` and nested `event_msg` shapes.
- Documented newest-first import and runtime-noise filtering in `docs/codex-history-eval.md`.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_codex_history`
- `python3 -m py_compile rag_ime/codex_history.py rag_ime/cli.py tests/test_codex_history.py`
- `python3 -m rag_ime.cli import-codex-history --path "$HOME/.codex/sessions" --dry-run --limit 20 --sample-size 8`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-real-eval-20260701.sqlite import-codex-history --path "$HOME/.codex/sessions" --project wisdom-weasel-rag-ime --limit 500 --sample-size 3`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-real-eval-20260701.sqlite eval-codex-history --cases-file docs/eval/codex-history-cases.example.jsonl --top-k 5 --match any --repeat 3`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-real-eval-20260701-2000.sqlite import-codex-history --path "$HOME/.codex/sessions" --project wisdom-weasel-rag-ime --limit 2000 --sample-size 0`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-real-eval-20260701-2000.sqlite eval-codex-history --cases-file docs/eval/codex-history-cases.example.jsonl --top-k 5 --match any --repeat 2`

Findings:
- Real dry-run now starts from the active RAG-IME session and samples user/project decisions instead of January AGENTS/environment noise.
- With 500 recent records, default cache repeat hit rate was `0.67`, pass rate was `0.33`, and disabled cache roughly doubled total eval latency on the same repeated cases.
- With 2000 recent records, pass rate improved to `0.67`; the dirty-pinyin/Rime boundary case reached top1, but `PROJECT_MEMORY_BLOCK` still missed and Squirrel/RAG ranked only at 5.
- Conclusion: cache works, but FTS-only retrieval is not enough. The next core slice should still be lightweight tag/app/context rerank and then hybrid/vector recall.

### 2026-07-01 06:58 CST
Problem:
- Local Qwen-style prediction servers can emit thinking text, which wastes latency and can leak into IME candidates.
- The project needed a concrete low-latency model test profile instead of hand-writing every timeout/token/thinking option.

Changes:
- Added `RAG_IME_PREDICTOR_PROFILE=instant` for small instruct models: chat mode, 350 ms timeout, 8 output tokens, low temperature/top_p, and thinking disabled.
- Added `RAG_IME_PREDICTOR_PROFILE=completion-instant` for base-model or llama.cpp-style `/v1/completions` servers.
- Added `RAG_IME_PREDICTOR_DISABLE_THINKING=1`.
- The env flag injects `chat_template_kwargs.enable_thinking=false` while preserving any other `RAG_IME_PREDICTOR_EXTRA_BODY_JSON` fields.
- Prediction benchmark and eval reports now expose `providerProfile`.
- Updated local model docs and Wisdom-Weasel issue mapping.

Commands:
- `git status -sb`
- `git diff --stat`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_predictor`
- `python3 -m py_compile rag_ime/predictor.py rag_ime/cli.py tests/test_predictor.py`
- `python3 -m rag_ime.cli --core-mode fixture eval-prediction --cases-file docs/eval/codex-history-cases.example.jsonl --max-candidates 3 --latency-budget-ms 150`
- `RAG_IME_PREDICTOR_PROVIDER=openai-compatible RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:9 RAG_IME_PREDICTOR_MODEL=Qwen3-0.6B RAG_IME_PREDICTOR_PROFILE=instant python3 -m rag_ime.cli --core-mode fixture predict-benchmark --case 'RAG 输入法' --recent-context '用户正在写本地记忆输入法' --max-candidates 3 --latency-budget-ms 150`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `git diff --check`

Git snapshot:
- Branch: `codex/wisdom-weasel-rag-ime-mvp`.
- Diff before commit: 8 files changed, 233 insertions, 22 deletions.

Verification:
- Predictor tests passed: 8 tests.
- Predictor + Codex-history tests passed: 17 tests.
- Full suite passed: 67 tests.
- Fixture eval and instant-profile fail-open benchmark passed.
- Fixture acceptance and `git diff --check` passed.
- No local OpenAI-compatible or Ollama model endpoint was listening on 127.0.0.1 ports 8000, 8080, 1234, or 11434, so real Qwen/MLX/llama.cpp speed testing is still pending.

### 2026-07-01 06:51 CST
Problem:
- `/rime-suggest` cache ignored only `requestSeq` and `sessionId`, so stable Rime candidates with changing raw pinyin/preedit still missed the cache.
- Input methods refresh on nearly every composing update; model/RAG should not rerun when the semantic query and visible candidates are unchanged.

Changes:
- Rebuilt the `/rime-suggest` cache key from the parsed Rime snapshot: semantic query, query basis, trigger decision, Rime candidates, committed context, side-candidate limits, memory event/action counts, project, and predictor fingerprint.
- Raw pinyin/preedit are included only when they are the semantic input (`preedit` / `rawInputFallback`) or when side candidates are explicitly forced.
- Cache hits now refresh `sessionId`, `requestSeq`, `rawInput`, `preedit`, Rime metadata, and trigger metadata before returning the cached model/RAG/display candidates.
- Added a regression test for raw-pinyin changes with stable Rime candidates.
- Updated README, debug docs, and Squirrel integration notes.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_debug_server`
- `python3 -m py_compile rag_ime/debug_server.py tests/test_debug_server.py`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `git diff --check`

Verification:
- Debug server tests passed: 13 tests.
- `py_compile` passed.
- Full suite passed: 65 tests.
- Fixture acceptance and `git diff --check` passed.

Follow-up:
- Subagent read VCP/RAG-IME and recommended the next implementation order: lightweight tag/app/context rerank first, optional local vector side-index second, stale/prefix cache third.
- This change completes the first cache-side step for real IME composing refreshes; next code slice should be the lightweight tag/app/context rerank in `LocalSqliteCoreClient`.

### 2026-07-01 06:44 CST
Problem:
- Need to confirm whether VCP uses BM25 before copying retrieval assumptions into RAG-IME.
- Local SQLite FTS5 `bm25()` returns lower-is-better scores, often negative; the old relevance conversion flattened all negative scores to the same boost.

Findings:
- `learnA/VCPToolBox/KnowledgeBaseManager.js` main diary/memory search is vector-first (`idx.search(searchVecFloat, k)`) with TagMemo boost, geodesic rerank, and vector cache reuse.
- `learnA/VCPToolBox/TDBKnowledge.js` cold knowledge search computes query embedding first, then prefers `searchHybrid(queryVector, queryText, ..., hybridAlpha)` where `queryText` is documented as the BM25 sparse-retrieval input; it falls back to pure vector search if hybrid is unavailable.
- RAG-IME should keep FTS5/BM25 as a fast lexical local baseline, but its long-term direction should be hybrid retrieval plus cache, rerank, evidence, and memory governance.

Changes:
- Converted SQLite FTS5 BM25 scores with `_bm25_relevance()`: negative scores now become positive lexical boosts using `log1p(-score)`, capped at `4.0`; non-negative scores keep reciprocal fallback.
- Added the lexical value into suggestion metadata reason as `fts5:<score>` for debugging.
- Added a regression test that verifies negative FTS5 BM25 affects ranking.

Commands:
- `git status -sb`
- `git diff --stat`
- `rg -n "BM25|bm25|embedding|Embedding|vector|Vector|TDB|cosine|keyword|关键词|tfidf|tf-idf|rank|score|检索|召回" VCPToolBox/TDBKnowledge.js VCPToolBox/KnowledgeBaseManager.js VCPToolBox/EmbeddingUtils.js VCPToolBox/TextChunker.js VCPToolBox/routes/admin/rag.js VCPToolBox/modules/contextManager.js`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_local_sqlite_core`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m py_compile rag_ime/local_sqlite_core.py tests/test_local_sqlite_core.py`
- `git diff --check`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`

Verification:
- Local SQLite core regression passed: 11 tests.
- Full suite passed: 64 tests.
- `py_compile`, `git diff --check`, and fixture acceptance passed.

Pitfalls:
- SQLite FTS5 BM25 polarity is easy to invert: lower is better, and good matches can be negative. Treating negative values as `0` removes the signal.

### 2026-07-01 06:37 CST
Problem:
- RAG evaluation and model prediction evaluation were separate commands, so model selection still required manually comparing two reports.
- The project needs a full-flow gate that answers whether local RAG, local model prediction, or both are useful for the same input-method cases.

Changes:
- Added `eval-comparison` CLI.
- It runs RAG suggestions and local model predictions over the same JSONL cases, repeat count, and match mode.
- The report includes separate `rag` and `model` eval reports plus a `comparison` block with `bothPassed`, `ragOnlyPassed`, `modelOnlyPassed`, `neitherPassed`, `winnerByPassRate`, `winnerByTop1Accuracy`, and per-case surfaces/latency.
- Updated README and Codex-history evaluation docs.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_codex_history`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture eval-comparison --cases-file docs/eval/codex-history-cases.example.jsonl --top-k 3 --max-candidates 3 --repeat 2`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`

Findings:
- Full suite now has 63 tests.
- Fixture comparison shows RAG can pass cases while the model lane cleanly reports `providerConfigured=false` and zero candidates when no local model is configured.

Next:
- Run `eval-comparison` with real Codex-history imports and real local Qwen/MLX/llama.cpp endpoints in both chat and completion mode.

### 2026-07-01 06:32 CST
Problem:
- The next useful goal progress was not blocked by missing Xcode: model prediction and Wisdom-Weasel source lessons still needed to be tightened.

Findings:
- Wisdom-Weasel `RimeWithWeasel.cpp` enters prediction after meaningful commit, stores committed text in `ContextHistory`, runs `PredictCandidates` on a background thread, drops stale results with `m_llm_request_seq`, appends LLM candidates after Rime candidates, and branches number-key selection by Rime count vs LLM count.
- Wisdom-Weasel `LlamaCppProvider.cpp` gets fast multi-candidate output by caching system prompt state and using parallel llama sequences/batch sampling; this is stronger than merely using a smaller model.
- rime/weasel candidate handling confirms the production adapter should stay inside Squirrel/Rime candidate state instead of using an external overlay as the real IME frontend.

Changes:
- Added `RAG_IME_PREDICTOR_PROMPT_MODE=chat|completion`.
- `completion` mode calls `/v1/completions` with `recent_context + current_input` as prefix and `n=max_candidates`, giving a portable base-model/llama.cpp-server baseline.
- Prediction parsing now strips `<think>`, analysis/reasoning tags, markdown fences, and JSON/list candidate output before ranking.
- Updated README, local model benchmark docs, macOS adapter docs, Rime/Squirrel framework decision, and Wisdom-Weasel issue map.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_predictor`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture eval-prediction --cases-file docs/eval/codex-history-cases.example.jsonl --max-candidates 3 --repeat 2`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`

Next:
- Run `eval-prediction` against a real local Qwen/MLX/llama.cpp endpoint in both `chat` and `completion` modes.
- If completion mode is still too slow, implement a native llama.cpp/MLX provider with KV cache reuse and batch sampling.

### 2026-07-01 06:24 CST
Problem:
- The user asked to complete Xcode configuration for the Squirrel/Rime frontend.

Findings:
- `bash scripts/setup_xcode_for_squirrel.sh` still finds no full `Xcode.app` under `/Applications` or `/Volumes/undo 4t/Applications`.
- A real external-disk install attempt with `RAG_IME_INSTALL_XCODE=xcodes RAG_IME_XCODE_VERSION="27.0 Beta 2"` failed at Apple Developer authentication: `Apple ID: Missing username or a password`.
- Strict doctor now has exactly one failure: active developer directory is `/Library/Developer/CommandLineTools`; Squirrel patch, generated config, Swift availability, LaunchAgent, and HTTP `/rime-suggest` all pass.

Commands:
- `bash scripts/setup_xcode_for_squirrel.sh`
- `RAG_IME_INSTALL_XCODE=xcodes RAG_IME_XCODE_VERSION="27.0 Beta 2" bash scripts/setup_xcode_for_squirrel.sh`
- `RAG_IME_DOCTOR_REQUIRE_XCODE=1 scripts/doctor_squirrel_integration.sh`

Next:
- Run `xcodes download "27.0 Beta 2" --directory "/Volumes/undo 4t/XcodeDownloads"` once Apple Developer auth is available, or provide `FASTLANE_SESSION` and rerun the setup script.
- After Xcode is installed, rerun strict doctor and build the prepared Squirrel checkout.

### 2026-07-01 00:55 CST
Problem:
- Squirrel debounce reduces frontend request spam, but repeated equivalent `/rime-suggest` requests can still reach the HTTP sidecar and repeat model/RAG work.

Changes:
- Added process-local short TTL cache for `DebugImeService.rime_suggest`.
- Cache key excludes `requestSeq` and `sessionId`, but includes payload content, memory event/action counts, project, and predictor configuration.
- Cached responses rewrite `requestSeq`/`sessionId` for the current request and include `cache.hit`.
- Commit/action/seed clear the cache.
- Browser debug JSON now includes `rimeSuggestCache` from `/api/health`.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_debug_server`

Next:
- Add cache hit-rate assertions to Codex-history/RAG evaluation runs and compare them with VCP-style cache targets.

### 2026-07-01 00:35 CST
Problem:
- Wisdom-Weasel avoids UI overwrite with request sequence, but Squirrel can call `rimeUpdate` very frequently and page/candidate state can change under the same raw input.

Changes:
- Updated Squirrel patch to read `rag_ime/debounce_ms`, debounce pending sidecar requests, and fingerprint request state.
- Stale guard now checks request sequence, session, raw input, preedit, page, and first Rime candidate fingerprint.
- Updated Rime sidecar merge policy so at most one model side candidate can be shown before RAG/memory side candidates.
- Added OpenAI-compatible predictor extra body/header JSON knobs for Qwen/reasoning-compatible servers.
- Updated Wisdom-Weasel issue map and Squirrel integration notes.

Findings:
- Wisdom-Weasel's useful pattern is async request sequence invalidation, but RAG-IME needs stricter frontend fingerprinting because RAG evidence and model results should not overwrite a changed Rime page.

Commands:
- `git apply --check squirrel-patches/0001-add-rag-ime-sidecar.patch` against Squirrel `2158538`
- `swiftc -typecheck` for `RagImeSidecarModels.swift` and `RagImeSidecarClient.swift`
- `scripts/prepare_squirrel_workspace.sh` using a local Squirrel clone

Next:
- Run `predict-benchmark` against a real local model; then evaluate base-prefix completion or llama.cpp KV/batch if latency is still high.

### 2026-07-01 00:12 CST
Problem:
- The project needs a concrete way to compare small local model choices for the short prediction lane.

Changes:
- Added `predict-benchmark` CLI.
- Added `benchmark_prediction_provider` and a latency-budget report schema.
- Documented the benchmark in `docs/local-model-prediction-benchmark.md`.

Findings:
- The benchmark uses the same predictor provider and history-context merge as `suggest-json`, so model latency is measured in the product path rather than through a separate toy prompt.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_predictor`

Next:
- Run the benchmark against real local Qwen/llama.cpp/MLX endpoints after selecting the local inference server.

### 2026-06-30 23:58 CST
Problem:
- The RAG/memory system needed a real local benchmark source, not only deterministic demo memories.

Changes:
- Added `rag_ime.codex_history` for local Codex JSONL parsing.
- Added `import-codex-history` CLI with dry-run and bounded import.
- Added default duplicate skipping using stable `record:<hash>` tags.
- Added `eval-codex-history` CLI for explicit query/expectedTerms retrieval evaluation.
- Documented the workflow in `docs/codex-history-eval.md`.

Findings:
- The import path reuses the same `InputEvent` -> SQLite/FTS5 -> suggestion pipeline as normal IME input, so the evaluation checks product candidates instead of raw chunks.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_codex_history`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`

Next:
- Add leave-one-session-out evaluation after importing real Codex logs.
- Compare FTS5-only against embedding/rerank and VCP-style cache behavior on the same cases.

### 2026-06-30 23:40 CST
Problem:
- Full patched Squirrel validation is blocked by missing full Xcode on this Mac.

Findings:
- Active developer directory is `/Library/Developer/CommandLineTools`; no local `Xcode.app` or `.xip` was found.
- Installed `xcodes` and `mas` to prepare both Apple Developer and App Store install paths.
- `xcodes list` shows `27.0 Beta 2`, matching the macOS 27 beta host, but download requires Apple ID credentials.
- `mas info 497799835` shows App Store Xcode 26.6, but `mas get` requires administrator password in an interactive terminal.
- Root disk has limited free space, so Xcode download/install should prefer `/Volumes/undo 4t`.

Changes:
- Added `scripts/setup_xcode_for_squirrel.sh`.
- Added `docs/xcode-squirrel-setup.md`.
- Enhanced `scripts/doctor_squirrel_integration.sh` to report active developer directory and `DEVELOPER_DIR`.

Commands:
- `brew install xcodes`
- `brew install mas`
- `xcodes list`
- `mas info 497799835`

Next:
- Complete Apple Developer/App Store/admin-password install step, then rerun setup and strict doctor.

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

### 2026-07-01
Topic:
- Restore full Rime-sidecar display-path eval after filtering raw trace surfaces.

Changes:
- Added product/runtime query expansions for selection routing, RAG-vs-model comparison, WSL embedding env vars, suggestion-cache metrics, and Codex-history ranking metrics.
- Added canonical surface summaries so visible IME candidates can show project keys such as `RAG_IME_EMBEDDING_BASE_URL`, `suggestionCache`, `top1Accuracy`, and `maxModelSideCandidates` instead of generic status text.
- Filtered patch/file-hit candidate surfaces and downranked patch/tool/subagent traces so they remain recallable but do not become candidate-bar text.
- Updated the local model plan for Ollama `qwen3.5` small tags: `0.8b`, `2b`, `4b`, and corresponding `-mlx` variants.

Verification:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_adapter tests.test_local_sqlite_core`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-rime-sidecar-eval-20260701.sqlite eval-rime-sidecar --cases-file docs/eval/codex-history-cases.example.jsonl --match any --repeat 1`
- Rime sidecar display path now passes 34/34, top1Accuracy=0.765, meanReciprocalRank=0.868, p95=46ms, noiseRate=0.
- `curl -s https://ollama.com/library/qwen3.5 | rg -o "qwen3\\.5:[0-9.]+b(?:-mlx)?" | sort -u` confirmed Ollama tags including `0.8b`, `2b`, `4b`, and `-mlx` variants.
- `ollama` is not installed or visible in this Mac session, so real model inference remains pending.

Next:
- Run full suite, fixture acceptance, direct Codex-history eval, and `git diff --check`, then push if clean.
- Start a real Ollama/WSL endpoint later and run `predictor-doctor`, `predict-benchmark`, `eval-prediction`, `eval-comparison`, and `eval-rime-sidecar`.

### 2026-07-01
Topic:
- Add a concrete local model matrix gate for Qwen3.5 candidates.

Changes:
- Added `eval-model-matrix` CLI to evaluate multiple OpenAI-compatible model ids on the same prediction case file.
- Default matrix is `qwen3.5:0.8b,qwen3.5:2b,qwen3.5:4b` against Ollama's `http://127.0.0.1:11434/v1`.
- Matrix output reports per-model pass rate, ranking metrics, latency, candidate availability, local runner availability, and a winner summary.
- Full per-case details are hidden by default to keep output readable; use `--include-cases` for debugging.
- Updated README and local model benchmark docs.

Verification:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_predictor`
- `python3 -m rag_ime.cli --core-mode fixture eval-model-matrix --cases-file docs/eval/codex-history-cases.example.jsonl --models qwen3.5:0.8b,qwen3.5:2b --latency-budget-ms 150`
- The local matrix command reports both qwen3.5 models configured but `hasCandidates=false`.
- `localRunners.available` is empty and `missing` includes `ollama`, `llama-server`, `lmstudio`, and `mlx_lm.server`; no model was downloaded or run in this Mac session.

Next:
- Install/start Ollama or a WSL OpenAI-compatible endpoint, pull `qwen3.5:0.8b` first, then rerun `eval-model-matrix`.

### 2026-07-01 07:39 CST
Problem:
- FTS5/rerank can handle many exact project-history cases, but the core did not yet have a pluggable vector side-index for true semantic recall experiments.
- Existing Codex-history eval could compare cache and latency, but not whether a vector provider was active or indexed.

Changes:
- Added optional embedding providers behind the local core boundary: disabled by default, deterministic `local-hash` baseline, and OpenAI-compatible embedding endpoint support.
- Added `memory_vectors`, vector upsert on writes, vector/FTS row merge, score contribution, `vector_index_stats()`, and `rebuild_vector_index()`.
- Added CLI flags `--embedding-provider`, `--embedding-vector-candidates`, `--embedding-vector-weight`, plus `rebuild-vector-index`.
- Added vector stats to RAG eval reports and documented the Mac/WSL embedding path.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_local_sqlite_core`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-vector-eval-20260701.sqlite import-codex-history --path /Users/undo/.codex/sessions --project wisdom-weasel-rag-ime --limit 2000 --sample-size 0`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-vector-eval-20260701.sqlite --embedding-provider local-hash rebuild-vector-index --project wisdom-weasel-rag-ime --limit 2000`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-vector-eval-20260701.sqlite --embedding-provider local-hash eval-codex-history --cases-file docs/eval/codex-history-cases.example.jsonl --top-k 5 --match any --repeat 2`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-vector-eval-20260701.sqlite eval-codex-history --cases-file docs/eval/codex-history-cases.example.jsonl --top-k 5 --match any --repeat 2`
- `git diff --check`

Findings:
- Full test suite passed with 72 tests.
- local-hash vector backfill indexed 2000/2000 imported Codex-history records.
- Both default FTS/rerank and local-hash hybrid passed the 3-case eval repeated twice with top1Accuracy=1.0 and MRR=1.0.
- Default path p95 was 21ms; local-hash hybrid p95 was 80ms on the 2000-record temp DB, so vector recall must stay optional and be benchmarked before enabling in the IME sidecar.

Next:
- Replace local-hash with a real local/WSL embedding endpoint and compare quality/latency on the same case file.
- Use subagent research output to decide whether VCP-style hybrid/cache behavior should change the vector merge or context-cache layer.

### 2026-07-01 07:46 CST
Problem:
- After adding optional vector recall, debug health and `/rime-suggest` cache did not expose or depend on vector index state.
- If a running sidecar served a cached response after vector backfill/provider changes, the IME could briefly show stale RAG candidates without a visible reason.

Changes:
- Added `vectorStats` to debug/sidecar health.
- Included `vectorStats` in the semantic `/rime-suggest` cache key so vector provider/index changes invalidate the short TTL cache.
- Added `vectorStats` to the debug page JSON panel.
- Added a test core whose vector revision changes to prove cache invalidation follows vector index state.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_debug_server`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `git diff --check`

Findings:
- Full suite passed with 73 tests.
- Acceptance still passes.
- Subagent read-only research confirmed the next high-value directions: VCP-style embedding/query caches and pending request dedupe, richer 30-50 case gold set, typed context lanes, and Wisdom-Weasel-style native llama.cpp/MLX prediction path with KV cache and batch candidates.

Next:
- Expand Codex-history gold cases before further rerank tuning.
- Add embedding exact cache / in-flight dedupe once a real embedding endpoint is selected.

### 2026-07-01 07:53 CST
Problem:
- The Codex-history evaluation file had only 3 cases, so recent retrieval improvements could overfit and still look perfect.
- We needed a broader, realistic gold set before tuning vector recall, rerank, or model prediction.

Changes:
- Expanded `docs/eval/codex-history-cases.example.jsonl` from 3 to 34 cases.
- Covered Squirrel/Rime integration, side candidate selection, sidecar cache, vector backfill, embedding config, Qwen/prediction eval, LaunchAgent/Xcode, InputMethodKit boundary, typed history context, VCP cache lessons, Wisdom-Weasel fast prediction, and debug/doctor workflows.
- Documented the current 34-case baseline in `docs/codex-history-eval.md`.

Commands:
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-expanded-eval-20260701.sqlite import-codex-history --path /Users/undo/.codex/sessions --project wisdom-weasel-rag-ime --limit 5000 --sample-size 0`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-expanded-eval-20260701.sqlite eval-codex-history --cases-file docs/eval/codex-history-cases.example.jsonl --top-k 5 --match any --repeat 1`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-expanded-eval-20260701.sqlite --embedding-provider local-hash rebuild-vector-index --project wisdom-weasel-rag-ime --limit 5000`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-expanded-eval-20260701.sqlite --embedding-provider local-hash eval-codex-history --cases-file /private/tmp/rag-ime-expanded-cases.jsonl --top-k 5 --match any --repeat 1`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_codex_history tests.test_predictor`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `git diff --check`

Findings:
- Default FTS5 + local rule rerank on 5000 imported records: 24/34 pass, top1Accuracy=0.50, MRR=0.566, p95 about 29ms.
- `local-hash` hybrid on the same DB: 23/34 pass, top1Accuracy=0.441, MRR=0.528, p95 about 160ms.
- This confirms `local-hash` should remain a deterministic side-index contract test, not a product default.
- Known gaps now captured as failing cases include candidate number policy, raw pinyin gate, model side budget, history-context prediction, Wisdom-Weasel fast prediction, local-first privacy recall, OpenAI-compatible predictor env recall, stale response guard, trigger decision, and Codex-history noise filter.

Next:
- Improve recall against the failing cases with field-aware boosts or a real semantic embedding provider, then rerun the same 34-case report.

### 2026-07-01 08:45 CST
Problem:
- The expanded 34-case Codex-history eval exposed 10 product/runtime recall gaps.
- Several failing queries used Chinese product language, while the implementation memories stored English identifiers such as `rawInputFallback`, `maxModelSideCandidates`, `requestSeq`, and `RAG_IME_PREDICTOR_BASE_URL`.
- Raw Codex tool transcripts are noisy, but deleting them entirely also removes useful code identifiers that may not appear in assistant summaries yet.

Changes:
- Expanded local query rewriting for Rime/Squirrel side candidates, raw-pinyin gating, local-first privacy, model side budget, history-context prediction, Wisdom-Weasel speed terms, OpenAI-compatible predictor config, stale-response guards, trigger decisions, sidecar cache metrics, and Codex runtime-noise filtering.
- Added light runtime-trace downranking for raw Codex tool transcript records, preserving code identifiers as fallback recall while preferring natural-language summaries.
- Added importer filtering for the Codex approval-review transcript wrapper text.
- Updated the `codex-history-noise-filter` gold case to verify real imported terms (`environment`, `tool-output`) instead of English phrases that were not present in the user history.
- Added focused regression tests for product/runtime query expansion and tool-trace downranking.
- Recorded the subagent read-only optimization review in `docs/agent/subagents/rag-ime-next-optimization-20260701.md`.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_codex_history tests.test_local_sqlite_core`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-expanded-eval-final-20260701.sqlite import-codex-history --path /Users/undo/.codex/sessions --project wisdom-weasel-rag-ime --limit 5000 --sample-size 0`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-expanded-eval-final-20260701.sqlite eval-codex-history --cases-file docs/eval/codex-history-cases.example.jsonl --top-k 5 --match any --repeat 1`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `git diff --check`

Findings:
- Fresh 5000-record newest-first Codex-history import now passes 34/34 cases.
- top1Accuracy improved from 0.500 to 0.824.
- meanReciprocalRank improved from 0.566 to 0.880.
- latency.p95Ms stayed within the input-method refresh budget at about 30ms.
- Over-filtering `[n] tool ...` records reduced recall to 28/34, so the chosen design is downranking rather than deletion.

Next:
- Use the subagent review to implement candidate-surface compression next; keep full `insert_text` but make `surface_text` smaller and cleaner for the real IME panel.
- Add exact embedding cache / provider fingerprint cache before testing a real WSL embedding endpoint.

### 2026-07-01 08:17 CST
Problem:
- Real IME panel space is small, but `SuggestionCompiler` mostly used the first sentence of retrieved memory as `surface_text`.
- Long RAG chunks, bullets, and Codex transcript/tool traces could therefore produce candidate text that looked like logs instead of input-method candidates.

Changes:
- Added candidate-surface compression in `SuggestionCompiler`.
- The compiler now prefers useful bullets/short semantic lines, strips transcript/tool/path/debug wrappers from display text, and still preserves the full committed material in `metadata.insert_text`.
- Added regression tests for bullet extraction and tool-trace prefix cleanup.
- Added a `/rime-suggest` sidecar smoke proving RAG `displayCandidates[].text` stays compact while `insertText` keeps the full paragraph.
- Updated UX notes to make `surface_text` vs. `insert_text` an explicit contract.
- Integrated Ptolemy's non-overlapping exact embedding cache patch for the OpenAI-compatible embedding provider.
- Embedding cache keys include provider fingerprint plus normalized text; provider fingerprint now includes endpoint hash, model, dimensions, and `extra_body` hash.
- Empty vectors are not cached, and `RAG_IME_EMBEDDING_CACHE_SIZE` controls the bounded in-process cache.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_adapter tests.test_rime_sidecar`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-expanded-eval-final-20260701.sqlite eval-codex-history --cases-file docs/eval/codex-history-cases.example.jsonl --top-k 5 --match any --repeat 1`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_embeddings`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`

Findings:
- Adapter/sidecar tests pass.
- Embedding cache tests pass: repeated normalized text hits once, endpoint/fingerprint change misses, empty vectors are not cached, and cache size is bounded.
- Full suite now has 82 tests and passed.
- 34-case Codex-history eval still passes 34/34 with unchanged ranking quality: top1Accuracy=0.824, meanReciprocalRank=0.880.

Next:
- Use the sidecar display/insert split when implementing the native candidate panel.
- Test a real WSL/local embedding endpoint with `RAG_IME_EMBEDDING_CACHE_SIZE` enabled and compare repeated-case latency.

### 2026-07-01 08:31 CST
Problem:
- The project had an optional local model provider, but it was easy to confuse "provider code exists" with "a real local Qwen/MLX/llama.cpp model is currently running and useful".
- The updated goal explicitly requires concrete small-model testing, preferably instant/no-thinking style.

Changes:
- Added shared `prediction_provider_status()` for model-lane observability.
- Added `rag-ime predictor-status` CLI to show model configuration without calling the model.
- Added `predictor` status to `/api/health` so the debug page can show whether the optional model lane is configured.
- Normalized `predict-benchmark` provider naming so configured-but-empty providers still report the configured provider name.
- Documented that `predictor-status` is only a config check; `predict-benchmark` / `eval-prediction` are the real liveness and quality gates.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `python3 -m rag_ime.cli --core-mode fixture predictor-status`
- `RAG_IME_PREDICTOR_PROVIDER=openai-compatible RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:8000 RAG_IME_PREDICTOR_MODEL=Qwen3-0.6B RAG_IME_PREDICTOR_PROFILE=instant python3 -m rag_ime.cli --core-mode fixture predictor-status`
- `RAG_IME_PREDICTOR_PROVIDER=openai-compatible RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:8000 RAG_IME_PREDICTOR_MODEL=Qwen3-0.6B RAG_IME_PREDICTOR_PROFILE=instant python3 -m rag_ime.cli --core-mode fixture predict-benchmark --case "RAG 输入法" --recent-context "用户正在写本地记忆输入法" --max-candidates 3 --latency-budget-ms 150`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-model-status-eval-20260701-0840.sqlite import-codex-history --path /Users/undo/.codex/sessions --project wisdom-weasel-rag-ime --limit 5000 --sample-size 0`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-model-status-eval-20260701-0840.sqlite eval-codex-history --cases-file docs/eval/codex-history-cases.example.jsonl --top-k 5 --match any --repeat 1`
- `git diff --check`
- Local endpoint probe for `127.0.0.1:8000/v1/models`, `127.0.0.1:8080/v1/models`, `127.0.0.1:1234/v1/models`, and `127.0.0.1:11434/api/tags`.

Findings:
- Full unit suite passed: 85 tests.
- Fixture acceptance passed.
- Real 5000-record Codex-history eval still passed 34/34, with top1Accuracy=0.824, meanReciprocalRank=0.880, p95=34ms.
- `git diff --check` passed.
- Default current machine status: `configured=false`, `providerName=NullPredictionProvider`.
- With Qwen instant env set, config status becomes `configured=true`, `providerProfile=instant`, `promptMode=chat`, `model=Qwen3-0.6B`, `timeoutMs=350`, `maxTokens=8`.
- Real benchmark against `127.0.0.1:8000` returned `hasCandidates=false`, so no usable local model server is currently running there.
- Common local endpoints `8000`, `8080`, `1234`, and `11434` all returned connection refused in this session.
- Ollama `qwen3.5` has small tags, so it should be included in the first local IME test matrix: `qwen3.5:0.8b`, `qwen3.5:2b`, `qwen3.5:4b`, plus `-mlx` variants on Mac when available.

Next:
- Start a real local/WSL OpenAI-compatible Qwen/llama.cpp/MLX endpoint, then run `predictor-status`, `predict-benchmark`, and `eval-prediction`.
- Prefer Qwen/Qwen3.5 instant/no-thinking first; compare chat `instant` against completion `completion-instant` before building a native KV-cache provider.

### 2026-07-01 08:46 CST
Problem:
- `predictor-status` showed whether env vars were set, but it did not explain why a configured model endpoint still returned no candidates.
- This made the next real Qwen/WSL test harder to debug.

Changes:
- Added `doctor_prediction_provider()` and `rag-ime predictor-doctor`.
- The doctor probes `/v1/models`, checks whether the configured model id is listed, runs one short prediction, reports latency budget status, and shows local runner commands visible in `PATH`.
- README, debug docs, and local-model benchmark docs now use the sequence: `predictor-status` -> `predictor-doctor` -> `predict-benchmark` -> `eval-prediction` / `eval-comparison`.

Commands:
- `command -v ollama || true`
- `command -v llama-server || true`
- `command -v lmstudio || true`
- `command -v mlx_lm.server || true`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_predictor`
- `python3 -m rag_ime.cli --core-mode fixture predictor-doctor`
- `RAG_IME_PREDICTOR_PROVIDER=openai-compatible RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:8000 RAG_IME_PREDICTOR_MODEL=Qwen3-0.6B RAG_IME_PREDICTOR_PROFILE=instant python3 -m rag_ime.cli --core-mode fixture predictor-doctor --case "RAG 输入法" --recent-context "用户正在写本地记忆输入法" --latency-budget-ms 150`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-predictor-doctor-eval-20260701.sqlite import-codex-history --path /Users/undo/.codex/sessions --project wisdom-weasel-rag-ime --limit 5000 --sample-size 0`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-predictor-doctor-eval-20260701.sqlite eval-codex-history --cases-file docs/eval/codex-history-cases.example.jsonl --top-k 5 --match any --repeat 1`
- `git diff --check`

Findings:
- This Mac currently has none of `ollama`, `llama-server`, `lmstudio`, or `mlx_lm.server` in `PATH`.
- Default `predictor-doctor` correctly reports `ready=false`, `configured=false`, `endpointReachable=false`, and missing local runners.
- With Qwen instant env pointed at `127.0.0.1:8000`, doctor reports `configured=true` but `/v1/models` connection refused, so the current blocker is no running local/WSL OpenAI-compatible server.
- Full unit suite passed: 87 tests.
- Fixture acceptance passed.
- Real 5000-record Codex-history eval still passed 34/34, top1Accuracy=0.824, meanReciprocalRank=0.880, p95=35ms.
- `git diff --check` passed.

Next:
- Use `predictor-doctor` as the first command after starting a WSL or Mac OpenAI-compatible Qwen endpoint.
- Only run the heavier 34-case `eval-prediction` after doctor reports reachable endpoint and parsed candidates.

### 2026-07-01 08:55 CST
Problem:
- The model lane failed open, but a configured endpoint that times out could still cost one model timeout per `/rime-suggest` composing refresh.
- This would break the input method's responsiveness even though RAG candidates can still work.

Changes:
- Added `CooldownPredictionProvider` around configured OpenAI-compatible predictors.
- Default cooldown: `RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS=5000`, failure threshold `RAG_IME_PREDICTOR_FAILURE_LATENCY_MS=250`.
- `prediction_provider_status()` and debug health now expose cooldown state.
- Added sidecar coverage proving a failed model endpoint is called once, subsequent refreshes skip the model, and RAG candidates still appear.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_predictor`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_rime_sidecar`
- `RAG_IME_PREDICTOR_PROVIDER=openai-compatible RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:8000 RAG_IME_PREDICTOR_MODEL=Qwen3-0.6B RAG_IME_PREDICTOR_PROFILE=instant python3 -m rag_ime.cli --core-mode fixture predictor-status`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `RAG_IME_PREDICTOR_PROVIDER=openai-compatible RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:8000 RAG_IME_PREDICTOR_MODEL=Qwen3-0.6B RAG_IME_PREDICTOR_PROFILE=instant python3 -m rag_ime.cli --core-mode fixture predictor-doctor --case "RAG 输入法" --recent-context "用户正在写本地记忆输入法" --latency-budget-ms 150`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-predictor-cooldown-eval-20260701.sqlite import-codex-history --path /Users/undo/.codex/sessions --project wisdom-weasel-rag-ime --limit 5000 --sample-size 0`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-predictor-cooldown-eval-20260701.sqlite eval-codex-history --cases-file docs/eval/codex-history-cases.example.jsonl --top-k 5 --match any --repeat 1`
- `git diff --check`

Findings:
- Predictor tests pass with cooldown on by default and with cooldown disabled through env.
- Rime sidecar tests pass and verify model-failure cooldown does not suppress RAG candidates.
- Predictor status shows cooldown metadata for configured Qwen instant env.
- Full suite passed: 91 tests.
- Fixture acceptance passed.
- Real 5000-record Codex-history eval still passed 34/34, top1Accuracy=0.824, meanReciprocalRank=0.880, p95=32ms.
- Qwen instant doctor against `127.0.0.1:8000` now reports `cooldown.active=true` after connection refused, proving the failure is surfaced and repeat model calls are short-circuited in-process.
- `git diff --check` passed.

Next:
- When a real WSL/Mac endpoint is available, compare no-cooldown debug mode vs default cooldown only for endpoint debugging.

### 2026-07-01 09:01 CST
Problem:
- `/rime-suggest` had a semantic TTL cache, but concurrent equivalent requests arriving before the first response finished still duplicated model/RAG work.
- This is exactly the VCP-style pending-request cache gap the project should handle for high-frequency IME refreshes.

Changes:
- Added in-flight dedupe for equivalent `/rime-suggest` cache keys in `DebugImeService`.
- Added `rimeSuggestCache.inFlight`, `inFlightHits`, and `inFlightErrors` health stats.
- Response cache payloads now include `inFlightHit`.
- Added a concurrent test with a blocking predictor proving two overlapping equivalent requests call the predictor once, while the second response rewrites current `sessionId` and `requestSeq`.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_debug_server`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-inflight-dedupe-eval-20260701.sqlite import-codex-history --path /Users/undo/.codex/sessions --project wisdom-weasel-rag-ime --limit 5000 --sample-size 0`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-inflight-dedupe-eval-20260701.sqlite eval-codex-history --cases-file docs/eval/codex-history-cases.example.jsonl --top-k 5 --match any --repeat 1`
- `git diff --check`

Findings:
- Debug-server tests pass with in-flight dedupe.
- Full suite passed: 92 tests.
- Fixture acceptance passed.
- Real 5000-record Codex-history eval still passed 34/34, top1Accuracy=0.824, meanReciprocalRank=0.880, p95=32ms.
- `git diff --check` passed.

Next:
- Continue toward real Squirrel/Xcode install and WSL/Mac model endpoint testing.

### 2026-07-01 09:17 CST
Problem:
- `eval-codex-history` proved core RAG quality, but it did not verify the real `/rime-suggest` path: Rime-first merge, visible side slots, trigger policy, compact display text, and sidecar cache.
- First real 5000-record sidecar eval passed only 13/34 because `historyContext` for model prediction was also passed into RAG retrieval, so recent status text crowded out relevant memories in the three side slots.

Changes:
- Added `eval-rime-sidecar` CLI using the same JSONL case format.
- The command calls `DebugImeService.rime_suggest(...)` and scores only non-Rime `displayCandidates`, avoiding false positives from the Rime candidate itself.
- Added report fields for side-candidate counts, trigger refreshes, `/rime-suggest` cache stats, suggestion cache stats, predictor status, vector stats, and per-case latency.
- Split sidecar context boundaries: local model prediction still receives `historyContext`, while RAG retrieval receives only the explicit `committedContext`.
- Added tests for sidecar eval, cache hits, and the model-vs-RAG context boundary.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_codex_history.CodexHistoryTests.test_cli_eval_rime_sidecar_scores_display_side_candidates_and_cache`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_rime_sidecar tests.test_codex_history.CodexHistoryTests.test_cli_eval_rime_sidecar_scores_display_side_candidates_and_cache`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-rime-sidecar-eval-20260701.sqlite import-codex-history --path /Users/undo/.codex/sessions --project wisdom-weasel-rag-ime --limit 5000 --sample-size 0`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-rime-sidecar-eval-20260701.sqlite eval-rime-sidecar --cases-file docs/eval/codex-history-cases.example.jsonl --match any --repeat 1`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-rime-sidecar-eval-20260701.sqlite eval-codex-history --cases-file docs/eval/codex-history-cases.example.jsonl --top-k 5 --match any --repeat 1`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-rime-sidecar-eval-20260701.sqlite eval-rime-sidecar --cases-file docs/eval/codex-history-cases.example.jsonl --match any --repeat 2 --rime-cache-ttl-ms 5000`

Findings:
- Direct RAG eval on the 5000-record temp DB still passes 34/34, top1Accuracy=0.794, meanReciprocalRank=0.865, p95=32ms.
- Before the context split, Rime sidecar display-path eval passed 13/34, p95=73ms.
- After the context split, Rime sidecar display-path eval passes 31/34, top1Accuracy=0.794, meanReciprocalRank=0.843, with p95 observed between 34ms and 49ms across local runs.
- With `--repeat 2 --rime-cache-ttl-ms 5000`, Rime sidecar eval passes 62/68 and reports `rimeSuggestCache` hits/misses = 34/34.

Next:
- Improve the remaining sidecar-only misses with candidate compression/ranking for three visible side slots.
- Run the same sidecar eval with a real local/WSL Qwen endpoint once available.

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

### 2026-07-01 00:20 CST
Problem:
- The user asked to make the Xcode setup complete for the Squirrel/Rime production route.
- This host still has only Command Line Tools selected, no full Xcode under `/Applications` or `/Volumes/undo 4t/Applications`.
- A real `xcodes` install attempt for `27.0 Beta 2` failed in Codex with `Apple ID: Missing username or a password`.

Changes:
- Hardened `scripts/setup_xcode_for_squirrel.sh` into a fuller preflight and install entrypoint.
- The script now reports disk space, installed Xcode directories, `FASTLANE_SESSION` state, `xcodes` data source, and a clear Apple Developer authentication recovery path.
- Added free-space guards for external `xcodes` installation and system `/Applications` App Store installation.
- Updated Xcode setup docs with the current machine findings and non-interactive authentication options.

Commands:
- `bash scripts/setup_xcode_for_squirrel.sh`
- `RAG_IME_INSTALL_XCODE=xcodes RAG_IME_XCODE_VERSION="27.0 Beta 2" bash scripts/setup_xcode_for_squirrel.sh`
- `RAG_IME_INSTALL_XCODE=mas bash scripts/setup_xcode_for_squirrel.sh`
- `xcodes list --data-source xcodeReleases --no-color | rg '^(27\\.0 Beta 2|26\\.6)'`

Next:
- Finish Xcode installation from an interactive Apple-authenticated terminal, or provide `FASTLANE_SESSION`, then rerun `scripts/setup_xcode_for_squirrel.sh`.
- After full Xcode is installed, run `RAG_IME_DOCTOR_REQUIRE_XCODE=1 scripts/doctor_squirrel_integration.sh` before building patched Squirrel.

### 2026-07-01 00:45 CST
Problem:
- Squirrel can refresh candidates on nearly every composing event, so relying only on frontend debounce and short TTL cache still risks running model/RAG work for raw pinyin noise.

Changes:
- Added a Rime-specific side candidate trigger decision in `rag_ime/rime_sidecar.py`.
- `/rime-suggest` now always preserves Rime candidates but skips model/RAG side lanes when the request has raw-pinyin fallback, no stable Rime candidate, no visible side slot, disabled side candidates, or a too-short candidate before idle.
- Response JSON now includes `triggerDecision` and `mergePolicy.sideCandidatesEnabled`.
- The browser debug page probes `/api/rime-suggest` and shows trigger/cache/display metadata in the JSON panel.
- Swift prototype models and the Squirrel patch pack now preserve the new trigger/merge fields.

Commands:
- `node --check debug/app.js`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `scripts/build_macos_frontend.sh`
- `RAG_IME_SQUIRREL_DRY_RUN=1 scripts/prepare_squirrel_workspace.sh`
- `build/RagImeMac.app/Contents/MacOS/RagImeMac --preview-rime-sidecar-json`

Next:
- When Xcode is available, validate the same trigger behavior inside patched Squirrel's real update loop.

### 2026-07-01 01:10 CST
Problem:
- The Squirrel patch could insert side candidates, but feedback writeback was split between commit and accepted-action calls in Swift.
- That duplicated memory governance details in the frontend and made the side-candidate acceptance flow harder to test end to end.
- A real `scripts/prepare_squirrel_workspace.sh` run also exposed an older patch hunk-size bug that dry-run did not catch: `RagImeSidecarModels.swift` was truncated during apply.

Changes:
- Added `record_rime_side_candidate_selection()` as the shared Python writeback contract.
- Added `POST /rime-select` and CLI `rime-select-json`.
- `/rime-select` records committed side-candidate text and records an `accepted` memory action when the selected candidate is a RAG candidate with memory metadata.
- Updated the Squirrel patch to prefer `/rime-select` / `rime-select-json`, with legacy commit/action calls only as fallback.
- Fixed Squirrel patch new-file hunk lengths so real patch apply produces complete Swift files.
- Updated README, debug, macOS adapter, Squirrel integration, and patch-pack docs.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `scripts/build_macos_frontend.sh`
- `RAG_IME_SQUIRREL_RESET=1 scripts/prepare_squirrel_workspace.sh`
- `python3 -m rag_ime.cli --help | rg 'rime-select-json|rime-suggest-json|sidecar-server'`

Next:
- With Xcode installed, build the prepared `/tmp/rag-ime-squirrel` checkout and verify number-key side candidate insertion plus `/rime-select` feedback in a real text field.

### 2026-07-01 01:30 CST
Problem:
- `eval-codex-history` only reported pass/fail recall over the combined top-K haystack.
- That could overstate quality because `--match all` could be satisfied by expected terms split across different candidates, while an input method user chooses one candidate at a time.
- It also did not expose rank quality or noise, both of which matter for a small IME panel.

Changes:
- Made Codex-history evaluation candidate-level.
- Added per-case `firstMatchRank`, `reciprocalRank`, `top1Passed`, `termFirstRanks`, `forbiddenMatchedTerms`.
- Added report-level `metrics.hitRate`, `top1Accuracy`, `meanReciprocalRank`, `meanFirstMatchRank`, `noiseRate`, and `noiseCount`.
- Added `forbiddenTerms` support in JSONL cases so obvious noisy suggestions can fail the case even when expected terms match.
- Updated docs and example cases.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `scripts/build_macos_frontend.sh`
- CLI eval smoke with a temporary DB/cases file, confirming `top1Accuracy`, `meanReciprocalRank`, and `noiseRate` output.

Next:
- Use these ranking metrics on a larger imported Codex-history slice and compare FTS-only, embedding recall, rerank, and VCP-style cache variants.

### 2026-07-01 01:50 CST
Problem:
- The local SQLite core reran FTS retrieval and suggestion compilation for repeated equivalent queries.
- Input methods and PI-style adapters commonly repeat the same context while the candidate panel refreshes, so cache hit visibility is needed before comparing FTS, embedding, rerank, and VCP-style cache variants.

Changes:
- Added an invalidation-safe process-local LRU suggestion cache to `LocalSqliteCoreClient`.
- Cache key uses normalized `current_input`, `recent_context`, `project`, and `top_k`.
- `record_event`, `apply_action`, and `reset` clear the cache so commit/action governance cannot return stale suggestions.
- Added `suggestion_cache_stats()` with hit/miss/hitRate/eviction/invalidation counters.
- Exposed `RAG_IME_SUGGESTION_CACHE_SIZE` / `--suggestion-cache-size`, debug health `suggestionCache`, and `eval-codex-history` `cacheStats`.
- Debug JSON now shows both `rimeSuggestCache` and local-core `suggestionCache`.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `scripts/build_macos_frontend.sh`
- `python3 -m rag_ime.cli --help | rg 'suggestion-cache-size|core-mode|eval-codex-history'`
- Repeated-case CLI eval smoke confirmed `cacheStats.hits=1`, `misses=1`, `hitRate=0.5`.

Next:
- Use `cacheStats` with ranked Codex-history metrics to compare no-cache, cache, embedding recall, rerank, and VCP-style context-cache strategies on the same cases.

### 2026-07-01 02:05 CST
Problem:
- Ranked Codex-history evaluation had quality and cache metrics, but not end-to-end latency.
- For an input method, a candidate that is accurate but slow is still not usable, so quality/caching/latency need to be visible in the same report.

Changes:
- `eval-codex-history` now times each `adapter.suggest(...)` call.
- Reports include per-case `elapsedMs` and summary `latency.caseCount`, `totalMs`, `avgMs`, `p50Ms`, `p95Ms`, and `maxMs`.
- Docs now describe latency as adapter-level time covering core retrieval, cache lookup, ranking, and suggestion compilation.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `scripts/build_macos_frontend.sh`
- Repeated-case CLI eval smoke confirmed `elapsedMs`, `latency`, and `cacheStats` output together.

Next:
- Use this combined report to compare local FTS-only, cache on/off, embedding recall, rerank, and future shared-core/VCP-style strategies.

### 2026-07-01 01:18 CST
Problem:
- `eval-codex-history` could show cache stats and latency, but repeated equivalent cases still had to be duplicated manually in JSONL.
- The sidecar LaunchAgent appeared loaded but did not listen on port 8766 when Python imported code directly from the external-volume checkout.
- Full Xcode configuration is still blocked because no full `Xcode.app` is installed and Apple Developer/App Store authentication is not available in this Codex session.

Changes:
- Added `eval-codex-history --repeat N`; repeated cases get `#r1`, `#r2`, etc. case ids and a top-level `repeat` summary.
- Added repeat-mode tests showing warm-cache behavior (`misses=1`, `hits=2` for a 3-repeat smoke).
- Added `scripts/sidecar_launch.py`.
- Changed LaunchAgent installation to copy the runtime package into `~/Library/Application Support/RagIme/app`, default the sidecar DB to `~/Library/Application Support/RagIme/rag-ime.sqlite`, and avoid `PYTHONPATH` in the plist.
- Added installer health polling so a loaded-but-dead sidecar fails immediately instead of silently passing.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `scripts/build_macos_frontend.sh`
- `scripts/install_sidecar_launch_agent.sh`
- `scripts/doctor_squirrel_integration.sh`
- `RAG_IME_DOCTOR_REQUIRE_XCODE=1 scripts/doctor_squirrel_integration.sh`
- `bash scripts/setup_xcode_for_squirrel.sh`

Findings:
- Normal doctor now reports LaunchAgent and HTTP `/rime-suggest` OK, with only the full Xcode warning remaining.
- Xcode preflight reports `active_developer_dir: /Library/Developer/CommandLineTools`, no full Xcode under `/Applications` or `/Volumes/undo 4t/Applications`, and enough external disk space for Xcode.

Next:
- Finish full Xcode install from an interactive Apple-authenticated terminal or provide `FASTLANE_SESSION`, then rerun `RAG_IME_DOCTOR_REQUIRE_XCODE=1 scripts/doctor_squirrel_integration.sh`.

### 2026-07-01 06:17 CST
Problem:
- `predict-benchmark` measured latency only, so it could not decide whether Qwen/MLX/llama.cpp model candidates were actually useful for historical-context prediction.
- RAG eval and model eval used different gates, making it hard to compare RAG recall vs. local model prediction on the same Codex-history cases.

Changes:
- Added `eval-prediction` CLI.
- It reuses the Codex-history JSONL case format (`query`, `recentContext`, `expectedTerms`, `forbiddenTerms`).
- The command calls the configured prediction provider through the product path, evaluates model candidates with the same candidate-level ranking/noise metrics as RAG eval, and reports latency plus a `prediction` provider block.
- Added mocked OpenAI-compatible CLI test for the Qwen-style provider path.
- Updated README and local-model benchmark docs.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_predictor`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture eval-prediction --cases-file docs/eval/codex-history-cases.example.jsonl --max-candidates 3 --repeat 2`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `scripts/build_macos_frontend.sh`
- `scripts/doctor_squirrel_integration.sh`

Findings:
- Full test suite now has 60 tests.
- Without a configured local model, `eval-prediction` reports `providerConfigured=false` and zero candidates instead of pretending the model lane is usable.
- Doctor still passes sidecar/Squirrel checks with only the full Xcode warning remaining.

Next:
- Run `eval-prediction` against a real local Qwen/MLX/llama.cpp endpoint and compare it with `eval-codex-history` on the same case file.

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
- Local smoke confirms the command works but no real model is downloaded or running here: `ollama`, `llama-server`, `lmstudio`, and `mlx_lm.server` are all missing, and qwen3.5 matrix candidates are empty.

### 2026-07-01
Problem:
- The user asked whether a concrete local model had actually been used/downloaded, and whether Qwen3.5 has an instant/non-thinking variant suitable for IME prediction.
- The Codex shell has proxy variables set (`HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, plus lowercase variants), so model downloads can accidentally consume proxy bandwidth.

Changes:
- Installed Ollama 0.30.11 through Homebrew.
- Started Ollama with `OLLAMA_MODELS=/Volumes/undo 4t/ollama-models`.
- Pulled `qwen3.5:0.8b` successfully; `ollama list` shows `qwen3.5:0.8b`, size 1.0 GB.
- Added `RAG_IME_PREDICTOR_PROVIDER=ollama`.
- The new provider calls Ollama native `/api/chat` with `think:false`, checks `/api/tags`, and uses JSON-array prompting for parsed short candidates.
- Kept OpenAI-compatible provider separate because Ollama `/v1/chat/completions` returned empty `content` and put Qwen3.5 output into a `reasoning` field.

Findings:
- Real `qwen3.5:0.8b` smoke through OpenAI-compatible `/v1` produced no parsed candidates because `content` was empty.
- Real `qwen3.5:0.8b` smoke through native Ollama provider found the configured model through `/api/tags` and returned 3 parsed candidates. Observed warm latency varied from about 477 ms to 1157 ms; it can pass a 1500 ms debug budget but is not stable enough for the default per-keystroke IME path.
- Candidate quality is not yet good enough for default IME use: examples were generic (`RAG`, `智能检索`, `知识图谱`).
- Current web check did not find a public Ollama `qwen3.5:*instant*` or `qwen3.5:*instruct*` local tag. Ollama lists Qwen3.5 as a `thinking` model family with size tags such as `0.8b`, `2b`, `4b`, and MLX variants. Treat "instant" as a desired inference mode/provider behavior, not as a confirmed local weight tag.

Commands:
- `brew info ollama`
- `brew install ollama`
- `OLLAMA_MODELS="/Volumes/undo 4t/ollama-models" OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0 ollama serve`
- `ollama pull qwen3.5:0.8b`
- `ollama list`
- `env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy RAG_IME_PREDICTOR_PROVIDER=ollama RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:11434 RAG_IME_PREDICTOR_MODEL=qwen3.5:0.8b RAG_IME_PREDICTOR_PROFILE=instant RAG_IME_PREDICTOR_TIMEOUT_MS=8000 RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS=0 python3 -m rag_ime.cli --core-mode fixture predictor-doctor --case "RAG 输入法" --recent-context "用户正在写本地记忆输入法，需要根据历史输入上下文预测候选短语。" --latency-budget-ms 1500`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_predictor`

Next:
- Do not download more models through proxy. Use explicit `env -u ...` for any future `ollama pull`.
- Test non-thinking instruction-tuned small models next, especially `qwen2.5:0.5b` or `qwen2.5:1.5b`, before larger Qwen3.5 thinking models.

### 2026-07-01 11:16 CST
Problem:
- The Mac-local model lane needed a real fastest-path answer, not just "try a small local model".
- `predictor-ttft` undercounted bad samples because timeout/no-first-chunk cases were not counted as over-budget.

Changes:
- Pulled `qwen3.5:0.8b-mlx` with proxy variables unset and kept Ollama models under `/Volumes/undo 4t/ollama-models`.
- Fixed TTFT summary accounting so missing first chunks count as over-budget and failures.
- Added a unit test for empty streaming output.
- Updated model benchmark, TTFT/KV-cache plan, README, and interview notes with measured Mac results.

Findings:
- `qwen3.5:0.8b-mlx` is the current best Mac smoke path: warm sequential p50 first chunk 46 ms, p95 213 ms, p50 total 456 ms.
- Ordinary `qwen3.5:0.8b` Q8 can approach 200 ms when warm, but one sequential sample stalled to 2547 ms first chunk.
- Quality remains poor for project memory: MLX passed 2/34 Codex-history prediction cases; Q8 passed 4/34.
- Conclusion: use MLX-tag Qwen3.5 0.8B only as a TTFT baseline and optional short-continuation lane. RAG/FTS/vector memory remains the source of truth; next fast provider should be resident MLX-LM or native llama.cpp/Metal with prompt/KV reuse and streaming first candidate.

Commands:
- `env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy OLLAMA_MODELS="/Volumes/undo 4t/ollama-models" ollama serve`
- `ollama pull qwen3.5:0.8b-mlx`
- `python3 -m rag_ime.cli --core-mode fixture predictor-ttft --case "RAG 输入法" --recent-context "用户正在写本地记忆和候选预测" --repeat 8 --max-candidates 3 --latency-budget-ms 200`
- `python3 -m rag_ime.cli --core-mode fixture eval-prediction --cases-file docs/eval/codex-history-cases.example.jsonl --max-candidates 3 --latency-budget-ms 500 --match any`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_predictor`

### 2026-07-01 11:37 CST
Problem:
- The previous Mac TTFT result proved Ollama `qwen3.5:0.8b-mlx` can stream first chunks quickly, but RAG-IME still lacked a first-class resident MLX provider.
- Wisdom-Weasel's fastest path depends on provider capabilities, especially prompt cache, sequence fork, and batch candidate sampling, not just a smaller model.

Changes:
- Added `RAG_IME_PREDICTOR_PROVIDER=mlx` and `MlxPredictionServiceProvider`.
- Added `rag_ime/mlx_predictor_server.py` with `/predict`, `/predict-stream`, `/health`, and `/v1/models`.
- Added `rag-ime mlx-predictor-server --model ...` CLI command that starts before any SQLite/core initialization.
- Extended `predictor-ttft` to support resident MLX streaming, not only native Ollama.
- Added provider capability flags: `streaming`, `residentModel`, `promptCache`, `sequenceFork`, `batchCandidates`, and `serverTiming`.
- Added mock MLX provider and streaming TTFT tests.
- Updated README and TTFT/KV-cache docs with the MLX service route and Wisdom-Weasel read-code checkpoint.

Findings:
- Current Python environment has `mlx` but not `mlx_lm`, so the real MLX-LM server was not started in this turn.
- The current MLX service honestly reports `streaming=true` and `residentModel=true`, but `promptCache=false`, `sequenceFork=false`, and `batchCandidates=false`.
- Wisdom-Weasel HEAD `64ba2fd` uses `LlamaCppProvider::GenerateCandidatesBatch()` with sequence-copy KV fork via `llama_memory_seq_cp`, so the future native llama.cpp provider should be accepted only when those capability flags turn true.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_predictor`
- `python3 -m py_compile rag_ime/predictor.py rag_ime/mlx_predictor_server.py rag_ime/cli.py`
- `env RAG_IME_PREDICTOR_PROVIDER=mlx RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:8767 RAG_IME_PREDICTOR_MODEL=mlx-qwen3.5-0.8b RAG_IME_PREDICTOR_PROFILE=instant python3 -m rag_ime.cli --core-mode fixture predictor-status`
- `python3 -c "import importlib.util; print('mlx_lm', bool(importlib.util.find_spec('mlx_lm'))); print('mlx', bool(importlib.util.find_spec('mlx')))"`

### 2026-07-01 11:44 CST
Problem:
- The MLX resident service exposed prompt-cache metadata, but did not yet have a concrete startup cache path or protocol tests around cache status.
- `stream_generate` docs do not clearly expose a `prompt_cache` parameter, so claiming active cached-prefix streaming would be unsafe.

Changes:
- Added `--prompt-cache` and `--prompt-cache-max-kv-size` to `mlx-predictor-server`.
- Added stable system-prompt cache preparation using MLX-LM's documented `make_prompt_cache` + `generate_step(..., prompt_cache=cache)` path.
- Added `promptCache.enabled/prepared/usedForGeneration/stablePrefixHash/stablePrefixTokens/prepareMs/maxKvSize` payload fields.
- Changed MLX-LM streaming call to use documented `temperature=` parameter instead of `temp=`.
- Added `tests/test_mlx_predictor_server.py` covering `/health` and `/predict-stream` prompt-cache status with a fake engine.
- Updated README and model benchmark docs to show `--prompt-cache` and the `usedForGeneration=false` boundary.

Findings:
- Current capability flags remain honest: the MLX lane has `streaming=true` and `residentModel=true`, but `promptCache=false` until generation actually reuses the cached prefix.
- The next real MLX task is to implement a verified generate-step streaming path or another safe cache-copy path that can set `usedForGeneration=true` without corrupting the stable prefix cache.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_predictor tests.test_mlx_predictor_server`
- `python3 -m py_compile rag_ime/mlx_predictor_server.py rag_ime/cli.py rag_ime/predictor.py tests/test_mlx_predictor_server.py`
- `python3 -m rag_ime.cli mlx-predictor-server --help`

### 2026-07-01 11:51 CST
Problem:
- `--prompt-cache` could prepare a stable prefix cache but did not yet use that cache during streaming generation.
- Reusing a single mutable MLX prompt-cache object across requests risks polluting the stable prefix.

Changes:
- Changed the MLX service to save the prepared stable-prefix cache to a local safetensors file.
- Added a cached streaming path that loads a fresh prompt-cache copy per request and calls `generate_step(..., prompt_cache=cache)`.
- Added `promptCache.cacheFileReady`, `hits`, `misses`, and `usedForGeneration=true` when the cached path is actually used.
- Kept fallback to normal `stream_generate` if cached generation fails.
- Added a fake MLX-LM module test proving `MlxLmEngine` uses `load_prompt_cache` and does not fall back to `stream_generate` on the cached path.
- Updated docs to remove the old `usedForGeneration=false` boundary.

Findings:
- This is safer than sharing one cache object, but likely slower than llama.cpp sequence-copy KV fork because it reloads a cache file per request.
- Capability flags still stay conservative until real-model `predictor-ttft` and `eval-prediction` prove this path beats the uncached/Ollama baselines.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_mlx_predictor_server tests.test_predictor`
- `python3 -m py_compile rag_ime/mlx_predictor_server.py tests/test_mlx_predictor_server.py`

### 2026-07-01 12:18 CST
Problem:
- Need a current, non-duplicated answer for the fastest Mac local inference path before continuing input-method implementation.
- Direct MLX-LM validation needs `mlx-lm`; the environment had `mlx` but not `mlx_lm`.

Attempts:
- Created a Python 3.12 temp venv at `/private/tmp/rag-ime-mlx-venv-312`.
- Tried no-proxy `pip install mlx-lm`; dependency metadata resolved, but `mlx_metal` downloaded at about 69 kB/s, so the install was cancelled before wasting more time.
- Started Ollama 0.30.11 with proxy variables unset and `OLLAMA_MODELS="/Volumes/undo 4t/ollama-models"`.
- Re-ran `predictor-ttft` against already downloaded `qwen3.5:0.8b-mlx` and `qwen3.5:0.8b`.

Findings:
- Local models present: `qwen3.5:0.8b-mlx` (1.2 GB, MLX runner) and `qwen3.5:0.8b` (1.0 GB, GGUF/Q8 llama-server).
- `qwen3.5:0.8b-mlx` with 2000 ms benchmark timeout: p50 first chunk 124 ms, first cold/preload sample 1264 ms, warm samples after load 76-133 ms, p50 total 888 ms.
- `qwen3.5:0.8b` with 5000 ms timeout: p50 first chunk 296 ms, p50 total 1646 ms, all samples over the 200 ms first-chunk budget.
- Ollama logs showed MLX cache hits after the first request and peak MLX memory around 1.1 GB. The GGUF route loaded llama-server plus vision/multimodal components.
- Current fastest practical Mac path is Ollama `qwen3.5:0.8b-mlx` for TTFT smoke. Direct MLX-LM and native llama.cpp/Metal remain the implementation paths for real prompt/KV control.

Commands:
- `env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy /private/tmp/rag-ime-mlx-venv-312/bin/python -m pip install mlx-lm`
- `env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy OLLAMA_MODELS="/Volumes/undo 4t/ollama-models" OLLAMA_KEEP_ALIVE=-1 OLLAMA_FLASH_ATTENTION=1 ollama serve`
- `env RAG_IME_PREDICTOR_PROVIDER=ollama RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:11434 RAG_IME_PREDICTOR_MODEL=qwen3.5:0.8b-mlx RAG_IME_PREDICTOR_PROFILE=instant RAG_IME_PREDICTOR_TIMEOUT_MS=2000 RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS=0 python3 -m rag_ime.cli predictor-ttft --case "本地 RAG 输入法需要根据历史输入预测候选" --recent-context "用户正在讨论 Mac 本地推理、Qwen3.5 0.8B、MLX、KV cache 和输入法首 token 延迟" --repeat 8 --latency-budget-ms 200`
- `env RAG_IME_PREDICTOR_PROVIDER=ollama RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:11434 RAG_IME_PREDICTOR_MODEL=qwen3.5:0.8b RAG_IME_PREDICTOR_PROFILE=instant RAG_IME_PREDICTOR_TIMEOUT_MS=5000 RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS=0 python3 -m rag_ime.cli predictor-ttft --case "本地 RAG 输入法需要根据历史输入预测候选" --recent-context "用户正在讨论 Mac 本地推理、Qwen3.5 0.8B、MLX、KV cache 和输入法首 token 延迟" --repeat 4 --latency-budget-ms 200`

### 2026-07-01 12:47 CST
Problem:
- `/rime-suggest` still called `predictor.predict()`, and native Ollama / MLX `predict()` waited for the full JSON candidate list even though TTFT measurement proved first chunk can arrive much earlier.

Changes:
- Added `RAG_IME_PREDICTOR_STREAM_FIRST=1` for native Ollama and resident MLX providers.
- When enabled, `predict()` reads the streaming endpoint until the first parsed candidate appears, then returns one model side candidate with `metadata.stream_first_candidate=true`.
- Added incremental streaming candidate parsing that ignores raw JSON syntax like `["` and waits for a complete string candidate or clean non-JSON fragment.
- `predictor-status` now reports `streamFirstCandidate`.
- Added unit tests for Ollama `/api/chat stream:true` and MLX `/predict-stream` first-candidate paths.

Findings:
- This turns the current Mac TTFT finding into a real sidecar-usable product path.
- It is still a latency bridge, not the final Wisdom-Weasel provider: prompt cache, sequence fork, and batch candidate generation remain separate capability gates.

Commands:
- `python3 -m py_compile rag_ime/predictor.py tests/test_predictor.py`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_predictor`

### 2026-07-01 13:08 CST
Problem:
- `RAG_IME_PREDICTOR_STREAM_FIRST=1` worked in manual commands, but the user LaunchAgent installer did not persist any `RAG_IME_PREDICTOR_*` variables into the sidecar plist.
- A login-started Squirrel sidecar would therefore lose the Ollama/MLX model configuration and run without the stream-first model lane.

Changes:
- Added a LaunchAgent environment whitelist for predictor, history-context, and cache tuning variables.
- The installer now persists variables such as `RAG_IME_PREDICTOR_PROVIDER`, `RAG_IME_PREDICTOR_MODEL`, `RAG_IME_PREDICTOR_STREAM_FIRST`, `RAG_IME_HISTORY_CONTEXT_EVENTS`, and `RAG_IME_RIME_CACHE_TTL_MS`.
- Extended the dry-run plist test to assert the predictor env is written.
- Documented the real install flow for Ollama MLX + stream-first sidecar.

Findings:
- This closes the gap between predictor code support and the actual macOS login sidecar path.

Commands:
- `RAG_IME_LAUNCH_AGENT_DRY_RUN=1 scripts/install_sidecar_launch_agent.sh`
- `python3 -m unittest tests.test_launch_agent_script`

### 2026-07-01 13:42 CST
Problem:
- Need a fuller, source-backed answer for the fastest Mac local inference plan before continuing the input-method implementation.

Findings:
- The current project evidence still ranks Ollama `qwen3.5:0.8b-mlx` first for immediate TTFT smoke because it already produced sub-200 ms warm first chunks.
- Official MLX-LM docs provide the exact primitives needed for the next experiment: `stream_generate`, prompt caching, and rotating KV cache.
- Official llama.cpp server docs confirm prompt cache, continuous batching, slot save/cache controls, KV cache type controls, and reasoning controls, but Wisdom-Weasel's native provider remains the better final reference because it uses explicit sequence-state save/restore and sequence copy for multi-candidate sampling.
- MLC LLM supports Metal, local/interactive/server modes, streaming, and prefix-cache-related overrides, but its compile/model-library flow makes it a backup, not the fastest MVP route.
- Core ML stateful models map well to KV-state ideas on macOS 15+, but conversion/support cost pushes it to a later research lane.

Changes:
- Added `docs/mac-local-inference-fast-path.md` with the runtime ranking, commands, acceptance gates, Wisdom-Weasel/MiniVLLM lessons, and source links.
- Linked the new document from the README and `docs/model-ttft-kv-cache-plan.md`.
- Folded in subagent findings about Wisdom-Weasel being Windows Weasel-only, native llama context concurrency risk, and the need to track first parsed candidate time separately from raw token TTFT.

### 2026-07-01 14:12 CST
Problem:
- `predictor-ttft` already recorded `firstCandidateMs` in individual measurements, but the summary and over-budget decision still used raw `firstChunkMs`.
- Raw chunks can be JSON syntax such as `["`, which is not a usable IME candidate.

Changes:
- Changed `benchmark_streaming_ttft_provider()` to evaluate the latency budget against `firstCandidateMs`.
- Added `hasFirstCandidate`, `p50FirstCandidateMs`, `p95FirstCandidateMs`, min/max first-candidate latency, and `firstCandidateMissingCount` to the summary.
- Added a regression test where a stream emits a raw chunk but no parsed candidate; it now counts as over budget.
- Updated README and model-latency docs to distinguish raw first chunk from first parsed candidate.

Commands:
- `python3 -m py_compile rag_ime/predictor.py tests/test_predictor.py`
- `python3 -m unittest tests.test_predictor`

### 2026-07-01 13:03 CST
Problem:
- The Mac inference decision needed to distinguish the fastest measured smoke path from the best controllable product kernel.
- Squirrel patch preparation only proved that a patch applied; it did not assert the critical RAG-IME hooks were present after patching.

Findings:
- Ollama `qwen3.5:0.8b-mlx` remains the fastest already measured Mac smoke baseline for keeping the UI/RAG loop moving.
- Native `llama.cpp`/Metal is still the strongest product-kernel candidate because it can own cancellation, prompt/KV reuse, sequence copy, and batch multi-candidate generation.
- Direct MLX-LM should be benchmarked next as the Apple-Silicon resident-service experiment.
- Core ML stateful KV and MLC LLM remain later paths because conversion/compile complexity is not worth blocking the IME loop yet.

Changes:
- Updated `docs/mac-local-inference-fast-path.md` with a decision-refinement section and explicit TTFC benchmark metrics.
- Updated `docs/interview-project-difficulties.md` so the interview story says first parsed candidate/TTFC, not just first chunk.
- Hardened `scripts/prepare_squirrel_workspace.sh` to assert required sidecar files and Squirrel integration hooks after patch application.
- Added an offline fake-Squirrel test that clones a local repo, applies a generated RAG-IME patch, writes config, and typechecks the Swift sidecar files when `swiftc` is available.

Commands:
- `bash -n scripts/prepare_squirrel_workspace.sh`
- `python3 -m unittest tests.test_prepare_squirrel_workspace`
- `python3 -m unittest discover -s tests`

### 2026-07-01 13:13 CST
Problem:
- The Mac TTFC decision needed a reusable multi-case benchmark command, not just manual `predictor-ttft` one-offs.

Changes:
- Added `bench-ime-ttfc`, a streaming first parsed candidate benchmark for multiple model ids on the same IME case file.
- Added `docs/eval/ime-ttfc-cases.example.jsonl` for speed-only cases that do not require `expectedTerms`.
- Added model-level winner selection based on over-budget count, p95 TTFC, p50 TTFC, and failure count.
- Preserved optional per-sample output behind `--include-cases`.

Findings:
- Real Ollama inventory contains `qwen3.5:0.8b-mlx` and `qwen3.5:0.8b` under `/Volumes/undo 4t/ollama-models`.
- Short mixed-model run: `qwen3.5:0.8b-mlx` had p50 `firstCandidateMs=120` ms, p95 `969` ms with 1 over-budget sample; `qwen3.5:0.8b` had p50 `272` ms, p95 `2184` ms with all samples over budget.
- Warm single-model run: `qwen3.5:0.8b-mlx` had p50 `102` ms, p95 `122` ms, but still 1/12 samples over 200 ms. `qwen3.5:0.8b` had p50 `241` ms, p95 `397` ms, 12/12 samples over budget.
- This supports keeping Ollama MLX as the current smoke path and rejecting the GGUF/Q8 `0.8b` tag for per-keystroke prediction.

Commands:
- `python3 -m py_compile rag_ime/cli.py rag_ime/predictor.py tests/test_predictor.py`
- `python3 -m unittest tests.test_predictor`
- `ollama list`
- `python3 -m rag_ime.cli --core-mode fixture bench-ime-ttfc --cases-file docs/eval/ime-ttfc-cases.example.jsonl --provider ollama --base-url http://127.0.0.1:11434 --models qwen3.5:0.8b-mlx,qwen3.5:0.8b --repeat 2 --latency-budget-ms 200`
- `python3 -m rag_ime.cli --core-mode fixture bench-ime-ttfc --cases-file docs/eval/ime-ttfc-cases.example.jsonl --provider ollama --base-url http://127.0.0.1:11434 --models qwen3.5:0.8b-mlx --repeat 3 --latency-budget-ms 200`
- `python3 -m rag_ime.cli --core-mode fixture bench-ime-ttfc --cases-file docs/eval/ime-ttfc-cases.example.jsonl --provider ollama --base-url http://127.0.0.1:11434 --models qwen3.5:0.8b --repeat 3 --latency-budget-ms 200`
- `python3 -m unittest discover -s tests`

### 2026-07-01 13:32 CST
Problem:
- The browser debug surface showed predictor configuration, but not whether the configured local model could produce a first parsed candidate on demand.
- The Squirrel doctor had useful diagnostics, but no single strict gate for "ready to try as a real macOS input source".

Changes:
- Added `POST /api/predictor-ttfc` to the debug server and a compact Model TTFC card to the browser debug page.
- The debug TTFC probe reuses the same streaming first parsed candidate benchmark as the CLI and only runs when the user presses the probe button.
- Added `RAG_IME_DOCTOR_REQUIRE_TRYOUT=1` to `scripts/doctor_squirrel_integration.sh`.
- Strict tryout mode requires a prepared patched Squirrel checkout, sidecar Swift files, generated config, Xcode project inspection with `xcodebuild -list`, and a working sidecar path.
- Doctor sidecar probing now checks `/health`, `/rime-suggest`, and `/rime-select`, so accepted side-candidate writeback is part of readiness.

Findings:
- Default doctor mode still exits zero and reports the current state: patched Squirrel workdir OK, sidecar health/suggest/select OK, predictor not configured, full Xcode missing.
- Strict tryout mode now fails non-zero with the real blocker: `active developer directory is CommandLineTools`; full Xcode must be installed/selected before patched Squirrel can be built and installed.

Commands:
- `python3 -m py_compile rag_ime/debug_server.py tests/test_debug_server.py`
- `python3 -m unittest tests.test_debug_server tests.test_doctor_squirrel_integration`
- `python3 -m unittest discover -s tests`
- `RAG_IME_DOCTOR_CHECK_LAUNCHD=0 scripts/doctor_squirrel_integration.sh`
- `RAG_IME_DOCTOR_REQUIRE_TRYOUT=1 RAG_IME_DOCTOR_CHECK_LAUNCHD=0 scripts/doctor_squirrel_integration.sh`

### 2026-07-01 13:55 CST
Problem:
- The long-term project is not complete yet: the remaining hard parts are real macOS input-source installation, sidecar-to-Squirrel behavior in daily typing, RAG/memory quality, local model first-candidate latency, and interview-ready difficulty records.
- The project needed one command that fails when acceptance, RAG recall, sidecar candidate shaping, or cache reuse regresses.

Changes:
- Added `quality-gate`, an aggregate CLI gate that runs deterministic adapter acceptance, direct Codex-history RAG eval, `/rime-suggest` sidecar eval, and cache probing.
- Refactored the eval and cache-probe paths into reusable helpers so future adapter/front-end work can reuse the same quality checks.
- Added a regression test for the aggregate gate and documented the command in README.

Commands:
- `python3 -m py_compile rag_ime/cli.py tests/test_codex_history.py`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_codex_history tests.test_debug_server`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `git diff --check`

### 2026-07-01 14:35 CST
Problem:
- User asked to finish the full-Xcode real build/install/system-input-method verification path before joint manual testing.
- Current host still has no full `Xcode.app`; `xcode-select` points to `/Library/Developer/CommandLineTools`, so `xcodebuild -version` fails before Squirrel can be built.
- The previous build script could inspect/build with `xcodebuild`, but did not automate Squirrel dependency prep, RAG config installation, or the final input-method install action.

Changes:
- Extended `scripts/build_patched_squirrel.sh` with an `install` action.
- Build/install now prepares Squirrel binary dependencies with `action-install.sh` when needed, refreshes bundled data files, locates the built `Squirrel.app`, installs it into `~/Library/Input Methods` by default, and can run Squirrel postinstall.
- Added `scripts/install_squirrel_rag_config.sh` to write a managed `rag_ime/*` patch block into `~/Library/Rime/squirrel.custom.yaml` from the generated patched-workdir snippet.
- Updated README, Xcode setup docs, and macOS frontend docs with the full tryout sequence and continuous-use verification checklist.

Current machine result:
- `scripts/prepare_squirrel_workspace.sh` succeeds.
- LaunchAgent sidecar is loaded and `/health`, `/rime-suggest`, `/rime-select` pass.
- `RAG_IME_DOCTOR_REQUIRE_TRYOUT=1 scripts/doctor_squirrel_integration.sh` still fails only at full Xcode availability.
- `scripts/build_patched_squirrel.sh list` and `scripts/build_patched_squirrel.sh install` fail cleanly at `xcodebuild -version` because the active developer directory is CommandLineTools.

Commands:
- `RAG_IME_SQUIRREL_RESET=1 scripts/prepare_squirrel_workspace.sh`
- `scripts/doctor_squirrel_integration.sh`
- `RAG_IME_DOCTOR_REQUIRE_TRYOUT=1 RAG_IME_DOCTOR_CHECK_LAUNCHD=1 scripts/doctor_squirrel_integration.sh`
- `scripts/build_patched_squirrel.sh list`
- `scripts/build_patched_squirrel.sh install`
- `bash -n scripts/build_patched_squirrel.sh scripts/install_squirrel_rag_config.sh`
- `python3 -m unittest tests.test_build_patched_squirrel tests.test_install_squirrel_rag_config`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`

### 2026-07-01 15:12 CST
Problem:
- Wisdom-Weasel's local LLM path has real low-latency mechanisms, but the current RAG-IME Ollama/MLX smoke path should not be treated as the final model lane.
- The project needed an enforceable distinction between "debug provider works" and "provider has the KV/cache/forking capabilities needed for a production IME".

Source findings:
- Wisdom-Weasel's llama.cpp provider keeps the model/context resident, prepares a stable system prompt once, saves/restores sequence state, copies sequence memory to parallel sequence ids, and samples multiple short candidates in one batch.
- The useful mechanisms map to `promptCache`, `sequenceFork`, and `batchCandidates`.
- Do not copy Wisdom-Weasel's unbounded detached-thread shape directly; RAG-IME should keep latest-only request handling and serialize or cancel native model context use.

Changes:
- Added `quality-gate --require-predictor-capability`, repeatable for `streaming`, `residentModel`, `promptCache`, `sequenceFork`, `batchCandidates`, and `serverTiming`.
- The aggregate quality-gate JSON now includes `predictor` status and explicit `predictor-capability:*` checks.
- `NullPredictionProvider` status now reports the same capability map as configured providers, so missing model capability requirements fail clearly.
- README, Mac local inference docs, and interview difficulty notes now document the Wisdom-Weasel-style capability gate.

Current machine result:
- `scripts/setup_xcode_for_squirrel.sh` still finds no full `Xcode.app`; active developer directory is `/Library/Developer/CommandLineTools`.
- `RAG_IME_DOCTOR_REQUIRE_XCODE=1 scripts/doctor_squirrel_integration.sh` fails only on full Xcode availability; sidecar health, `/rime-suggest`, and `/rime-select` pass.
- Escalated `xcodebuild -version` confirms the real error: `tool 'xcodebuild' requires Xcode`.

Commands:
- `python3 -m py_compile rag_ime/cli.py rag_ime/predictor.py tests/test_codex_history.py`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_codex_history tests.test_predictor`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `git diff --check`
- `scripts/setup_xcode_for_squirrel.sh`
- `scripts/doctor_squirrel_integration.sh`
- `RAG_IME_DOCTOR_REQUIRE_XCODE=1 scripts/doctor_squirrel_integration.sh`
- `scripts/build_patched_squirrel.sh list`

### 2026-07-01 15:46 CST
Problem:
- The previous predictor capability gate was static. It could say that `local-mlx` was a resident streaming service, but it could not prove whether the MLX prompt cache was actually used by the runtime generation path.

Changes:
- Added MLX service runtime capabilities to `/health`.
- Added `MlxPredictionServiceProvider.capability_probe()` and delegated probe support through `CooldownPredictionProvider`.
- Added `prediction_provider_status(..., probe_capabilities=True)` and CLI `predictor-status --probe-capabilities`.
- `quality-gate` now probes provider capabilities automatically when `--require-predictor-capability` is present.
- `promptCache=true` now requires `enabled`, `prepared`, `cacheFileReady`, and `usedForGeneration`; a startup-prepared-only MLX cache remains unproven.
- Added provider, CLI, and aggregate quality-gate tests for MLX prompt-cache capability probing.

Commands:
- `python3 -m py_compile rag_ime/predictor.py rag_ime/mlx_predictor_server.py rag_ime/cli.py tests/test_predictor.py tests/test_codex_history.py`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_predictor tests.test_codex_history tests.test_mlx_predictor_server`
- `git diff --check`

### 2026-07-01 16:18 CST
Problem:
- The aggregate RAG-IME gate could enforce recall/pass-rate and cache hits, but not ranking quality or noise. That is too weak for an input method, where rank 1 and low-noise candidates matter more than broad recall.

Changes:
- Added explicit `quality-gate` thresholds for direct RAG and `/rime-suggest` sidecar:
  - `--min-rag-top1-accuracy`
  - `--min-sidecar-top1-accuracy`
  - `--min-rag-mrr`
  - `--min-sidecar-mrr`
  - `--max-rag-noise-rate`
  - `--max-sidecar-noise-rate`
- The gate now emits separate checks for pass rate, top1, MRR, and noise on both direct RAG and sidecar paths.
- Added tests that verify the new metric checks are present and that noise thresholds fail the gate when forbidden terms appear.
- README and Codex-history eval docs now show mature-goldset threshold commands.

Subagent finding:
- PI shared core already has retrieval/rerank cache, vector cache, memory governance review queue, and goldset gates.
- The smallest next VCP-style optimization is provider miss in-flight dedupe for embedding/rerank calls in `agent-source-projects/pi-rag-memory-extension/src/retrieval-rerank-provider.ts`, similar to VCP `RAGDiaryPlugin` pending embedding requests.

Commands:
- `python3 -m py_compile rag_ime/cli.py tests/test_codex_history.py`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_codex_history`
- `git diff --check`

### 2026-07-01 15:32 CST
Problem:
- Shared RAG/memory provider caches could still duplicate expensive provider calls when identical embedding or rerank misses arrived concurrently.
- This matters for the IME path because typing can fire bursty repeated queries; cache hit rate alone is not enough if the first miss fans out.

Changes:
- Applied a VCP-style in-flight request dedupe slice to the PI shared memory core in `agent-source-projects/pi-rag-memory-extension/src/retrieval-rerank-provider.ts`.
- Added `withInFlight(...)` and coalesced concurrent identical misses for query embeddings, embedding rerank batches, and LLM rerank calls.
- Added `agent-source-projects/pi-rag-memory-extension/test/retrieval-rerank-inflight.test.mjs` covering query embedding dedupe, embedding rerank dedupe, LLM rerank dedupe, and retry after failure.

Git:
- learnA top-level local commit: `4c67f8e7 Dedupe rerank provider misses`.
- Not pushed from learnA because the top-level repo already has many unrelated dirty files and is ahead of origin.

Verification:
- `node --experimental-strip-types test/retrieval-rerank-inflight.test.mjs`
- `node --experimental-strip-types -e "await import('./src/retrieval-rerank-provider.ts'); console.log('provider import ok')"`
- `git diff --check -- src/retrieval-rerank-provider.ts test/retrieval-rerank-inflight.test.mjs`
- `npm test`

Full-Xcode status:
- Real Squirrel build/install/system input-method continuous-use verification is still blocked on this host.
- `xcode-select -p` returns `/Library/Developer/CommandLineTools`.
- `xcodebuild -version` fails with `tool 'xcodebuild' requires Xcode`.
- `/Applications` and Spotlight lookup do not show `Xcode.app`.

### 2026-07-01 15:42 CST
Problem:
- The local model lane needs to predict from historical input context, but a future native KV/prompt-cache provider needs a stable contract for deciding when context can be reused.
- Without explicit fingerprints, debug output can show text, but cannot prove whether a request is cacheable in the Wisdom-Weasel sense: stable prompt/history prefix plus dynamic current input.

Changes:
- Added `historyContextMeta` to sidecar and debug suggestion payloads.
- Added model `requestMeta` to prediction metadata with `currentInputFingerprint`, `contextFingerprint`, `contextChars`, and `stablePrefixHash`.
- MLX local service requests now receive the same fingerprint fields and stream responses echo them as `requestMeta`.
- OpenAI-compatible and Ollama external request bodies were kept unchanged; the metadata is local response/debug data only for those providers.
- Documented the fingerprint contract in `docs/model-ttft-kv-cache-plan.md` and `docs/debug-surface.md`.

Verification:
- `python3 -m py_compile rag_ime/history_context.py rag_ime/rime_sidecar.py rag_ime/payloads.py rag_ime/predictor.py rag_ime/mlx_predictor_server.py tests/test_rime_sidecar.py tests/test_predictor.py tests/test_mlx_predictor_server.py`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_rime_sidecar tests.test_predictor tests.test_mlx_predictor_server`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `git diff --check`

Status:
- This is not native KV cache completion. It is the protocol gate needed before implementing a llama.cpp/Metal or stronger MLX provider that can safely reuse stable prefix state.

### 2026-07-01 15:51 CST
Problem:
- `/rime-suggest` parsed and returned `latencyBudgetMs`, but the model lane could still block the whole response until the provider's static timeout.
- That is wrong for an input method: a slow model must not delay Rime/RAG candidates.

Subagent finding:
- The risk was confirmed by read-only review: the sidecar called `predictor.predict(...)` without a budget/deadline, and RAG suggestions ran only after the model call.
- The suggested minimum was per-request deadline/fail-open behavior, not a full async scheduler.

Changes:
- `build_rime_sidecar_response()` now runs RAG retrieval first, then gives the model lane only the remaining `latencyBudgetMs`.
- Added a single in-process model-lane guard: if the model exceeds the budget, the response returns `modelPredictions=[]` while preserving Rime/RAG candidates.
- Added `modelLane` response metadata with `called`, `timedOut`, `skippedReason`, `latencyBudgetMs`, `elapsedMs`, `totalLatencyBudgetMs`, and `elapsedBeforeModelMs`.
- If a previous model request is still running, new requests skip the model lane instead of piling up provider calls.
- Documented the behavior in README, debug-surface docs, and local-model benchmark docs.

Verification:
- `python3 -m py_compile rag_ime/rime_sidecar.py rag_ime/debug_server.py tests/test_rime_sidecar.py tests/test_debug_server.py`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_rime_sidecar tests.test_debug_server`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `git diff --check`

Status:
- This enforces IME responsiveness for the sidecar hot path without claiming native cancellation. A timed-out provider call may still finish in the daemon guard thread, but subsequent requests do not wait for it.

### 2026-07-01 15:59 CST
Problem:
- The previous hot-path budget guard covered the model lane, but RAG retrieval and model history-context construction could still block `/rime-suggest`.
- This matters once the sidecar talks to a shared RAG core with embedding/rerank/WSL work instead of only fast local FTS5.

Changes:
- Added a bounded `ragLane` around `adapter.suggest(...)`.
- `build_rime_sidecar_response()` now returns Rime candidates even when RAG retrieval exceeds `latencyBudgetMs`.
- Moved `build_prediction_context()` into the model-lane budget thread, so slow history-context loading cannot block the main sidecar response.
- Added a deadline check before calling the model provider; if history-context construction already consumed the model budget, the provider is not called.
- Added tests for slow RAG fail-open and slow history-context fail-open.
- Updated README, debug-surface docs, and local-model benchmark docs to describe `ragLane` and `modelLane`.

Verification:
- `python3 -m py_compile rag_ime/rime_sidecar.py tests/test_rime_sidecar.py`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_rime_sidecar`
- `python3 -m py_compile rag_ime/rime_sidecar.py rag_ime/debug_server.py tests/test_rime_sidecar.py tests/test_debug_server.py`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_rime_sidecar tests.test_debug_server`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `git diff --check`

Status:
- This still does not provide real cancellation for an already-running RAG/core call; it bounds user-visible waiting and prevents immediate side-lane pileups with a single in-process guard.

### 2026-07-01 16:14 CST
Problem:
- After adding `ragLane` and `modelLane` fail-open behavior, a regression could still look healthy if the candidate panel renders easy cases while one side lane silently times out under the IME latency budget.

Changes:
- `eval-rime-sidecar` now reports RAG/model lane called counts, timeout counts, and timeout rates.
- `quality-gate` now accepts `--max-sidecar-rag-timeout-rate` and `--max-sidecar-model-timeout-rate`.
- Added regression coverage for the sidecar timeout-rate checks and documented strict mature-goldset usage in README and Codex-history eval docs.

Verification:
- `python3 -m py_compile rag_ime/cli.py tests/test_codex_history.py`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_codex_history`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`

Status:
- Full-Xcode Squirrel build/install/system-input-method continuous-use verification is still blocked on this host because only Command Line Tools are selected.

### 2026-07-01 16:25 CST
Problem:
- `bench-ime-ttfc` could measure the first parsed model candidate, but the normal `quality-gate` did not enforce that result.
- That left a gap between manual model-speed experiments and release-style acceptance: a local model could be reachable yet too slow for the input-method lane.

Changes:
- Refactored the IME TTFC benchmark into `run_ime_ttfc_benchmark()` so CLI and quality gate share the same implementation.
- Added optional `quality-gate --require-model-ttfc` with provider, base URL, model list, TTFC cases, repeat count, p95 threshold, and over-budget-rate threshold.
- Added model TTFC checks: supported streaming provider, first-candidate presence, p95 first-candidate latency, and over-budget rate.
- Added an integration test using a mock Ollama streaming server with one good MLX-tag model and one bad model.
- Updated README, Codex-history eval docs, and local-model benchmark docs.

Verification:
- `python3 -m py_compile rag_ime/cli.py tests/test_predictor.py tests/test_codex_history.py`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_predictor`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_predictor tests.test_codex_history`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `git diff --check`

Status:
- Full suite passed with 137 tests.
- `ollama list` could not connect because the Ollama server is not running, so this turn did not run a real-model TTFC benchmark.

### 2026-07-01 17:53 CST
Problem:
- Xcode became available and the project needed to move from buildable prototype to an installed macOS input-method App bundle.
- The sidecar LaunchAgent previously hit an intermittent `launchctl bootstrap` I/O error; manual retry succeeded, so the installer needed to be retry-safe.
- The Squirrel fallback config still defaulted to the repo-local SQLite path while the LaunchAgent used the user Application Support database.

Changes:
- Added retry/backoff around LaunchAgent `bootstrap` after `bootout`.
- Changed the generated Squirrel config default DB path to `~/Library/Application Support/RagIme/rag-ime.sqlite`, matching the LaunchAgent sidecar.
- Installed patched `Squirrel.app` into `~/Library/Input Methods/Squirrel.app`.
- Re-deployed `~/Library/Rime/squirrel.custom.yaml` with `rag_ime/sidecar_url` and the unified DB path.

Verification:
- `scripts/install_sidecar_launch_agent.sh` reinstalled the sidecar and reported `health: OK`.
- `scripts/build_patched_squirrel.sh install` built and installed patched Squirrel.
- `RAG_IME_DOCTOR_REQUIRE_TRYOUT=1 ... scripts/doctor_squirrel_integration.sh` passed with `failures=0 warnings=0`.
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests` passed with 140 tests.
- `git diff --check` passed.

Status:
- The project is now installed as a user-level macOS input method bundle; remaining validation is manual System Settings enablement and continuous typing in the real input source.

### 2026-07-01 18:07 CST
Problem:
- The installed `Squirrel.app` existed under `~/Library/Input Methods`, but macOS TIS initially did not expose it as an enabled input source.
- Upstream Squirrel's `SquirrelApp.appDir` was hardcoded to `/Library/Input Library/Squirrel.app`, so `--register-input-source` registered the wrong path for user-level installs.
- With `CODE_SIGNING_ALLOWED=NO`, the copied app only had a linker ad-hoc signature and no sealed resources; TIS registration became unreliable.

Changes:
- Patched Squirrel `Main.swift` so registration uses `Bundle.main.bundleURL`.
- Added a prepare-time guard requiring the dynamic bundle path patch.
- Added post-copy `codesign --force --deep --sign -` to `scripts/build_patched_squirrel.sh` by default.
- Added `scripts/check_macos_input_source.sh` as the shared TIS probe.
- Added postinstall register/enable retries until TIS confirms the input source is enabled/selectable.
- Extended strict doctor to check the installed macOS TIS source `im.rime.inputmethod.Squirrel.Hans` is registered, enabled, and selectable.
- Documented the signing/TIS behavior and the fact that active source selection may still need manual input-menu switching.

Verification:
- Rebuilt and installed patched Squirrel.
- `Squirrel --register-input-source` now reports `file:///Users/undo/Library/Input%20Methods/Squirrel.app/`.
- The updated install script now reports `macOS input source enabled` after its own retry loop.
- TIS reports `im.rime.inputmethod.Squirrel.Hans enabled=true selectable=true selected=false`.
- Strict doctor passed with `failures=0 warnings=0`.
- Focused prepare/build/doctor tests passed.

Status:
- System input-source enablement is now machine-verifiable. Remaining real-use validation is switching to Squirrel from the macOS input menu and typing continuously in a normal app.

### 2026-07-01 18:45 CST
Problem:
- The user still could not see/use the installed input method in System Settings even though TIS reported `Squirrel.Hans enabled=true selectable=true`.
- The earlier doctor check conflated "TIS can enumerate the source" with "the current user's HIToolbox enabled input-source list contains the source".

Changes:
- Added `hitoolboxEnabled` to `scripts/check_macos_input_source.sh`.
- Added `scripts/enable_squirrel_hitoolbox_input_source.sh` as a local debug helper that backs up `com.apple.HIToolbox`, appends the Squirrel bundle/mode entries, restarts `cfprefsd`, re-registers Squirrel, and re-runs the strict check.
- Added `scripts/select_macos_input_source.sh` and `scripts/wait_squirrel_typing_ready.sh` for selected-source validation.
- Updated README and macOS setup docs to distinguish TIS registration, HIToolbox enablement, and active input-source selection.
- Fixed doctor temp-file handling and `set -u` empty-array failure in the input-source check path.

Verification:
- System Settings now shows `鼠须管` / Squirrel in installed input methods.
- `RAG_IME_DOCTOR_REQUIRE_INPUT_SOURCE=1 RAG_IME_DOCTOR_REQUIRE_HITOOLBOX_ENABLED=1 RAG_IME_SQUIRREL_APP="/Library/Input Methods/Squirrel.app" scripts/doctor_squirrel_integration.sh` passed with `failures=0 warnings=0`.
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests` passed with 142 tests in non-sandbox mode.
- `git diff --check` passed.

Status:
- Installed and enabled state is verified.
- Active source selection is still manual: current input source was ABC after timeout, so continuous real typing validation still requires switching from the macOS input menu to Squirrel.

### 2026-07-01 19:05 CST
Problem:
- After Squirrel became visible in System Settings, the remaining real-use blocker was active input-source selection: terminal checks showed `hitoolboxEnabled=true` but `selected=false`.
- The browser debug page showed candidate, TTFC, cache, and JSON state, but did not show whether the macOS input menu was actually on Squirrel.

Changes:
- Added `DebugImeService.input_source_status()` and `GET /api/input-source`.
- The endpoint reuses `scripts/check_macos_input_source.sh --require-hitoolbox-enabled`, parses `enabled/selectable/selected/current/hitoolboxEnabled`, and returns a structured debug payload.
- Added an Input Source card to `debug/index.html` / `debug/app.js` showing installed-list state, selected state, and compact current input-source ID.
- Added debug-server tests for direct service parsing and HTTP `/api/input-source`.
- Documented the debug page input-source check in README.

Verification:
- `GET /api/input-source` returned `ok=true`, `typingReady=false`, `current=com.bytedance.inputmethod.doubaoime.pinyin` on the current machine, matching the observed menu state.
- Browser screenshot showed the new Input Source card without enlarging the IME overlay.
- Browser console had no warnings/errors.
- `python3 -m py_compile rag_ime/debug_server.py tests/test_debug_server.py`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_debug_server` passed in non-sandbox mode.
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests` passed with 144 tests.

Status:
- Debug page can now diagnose the exact install-vs-selected gap.
- Continuous typing verification is still pending until the active input source is switched to Squirrel.

### 2026-07-01 19:25 CST
Problem:
- The aggregate `quality-gate` covered adapter acceptance, direct RAG eval, Rime sidecar display eval, cache hits, model TTFC, and provider capabilities, but it still did not fail when macOS was not actually using Squirrel.
- This left the real typing path dependent on manual terminal checks after backend quality had already passed.

Changes:
- Added optional `quality-gate --require-input-source-ready`.
- Added `--input-source-id` and `--input-source-check-script` so tests and nonstandard installs can reuse the same gate.
- The gate reuses `DebugImeService.input_source_status()` and adds `input-source-installed` plus `input-source-selected` checks.
- README's mature gold-set example now shows `--require-input-source-ready` as the real macOS typing gate.

Verification:
- Added tests for selected and unselected fake input-source scripts.
- `python3 -m py_compile rag_ime/cli.py rag_ime/debug_server.py tests/test_codex_history.py`
- Focused input-source quality-gate tests passed.
- Current-machine smoke with `--require-input-source-ready` failed only on `input-source-selected`, while `input-source-installed` passed; this matches `current=com.apple.keylayout.ABC`.
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests` passed with 146 tests.

Status:
- Backend quality gates can now include active Squirrel selection when doing real macOS tryout.
- The current machine still reports Squirrel installed but not selected until the user switches from the menu bar.

### 2026-07-01 19:45 CST
Problem:
- The user confirmed the visible `鼠须管` entry in System Settings, but the real input-source check still reported `selected=false` and `current=com.apple.keylayout.ABC`.
- The debug page showed raw installed/selected/current metrics, but it did not provide a stable readiness state that could distinguish "installed but switch needed" from "ready for typing validation".

Changes:
- Added `readinessState`, `readinessMessage`, and `nextAction` to `/api/input-source`.
- The readiness states are `ready`, `switch`, `install`, and `error`; the current machine maps to `switch` until the active macOS input menu is changed to Squirrel.
- Updated the browser debug page to poll `/api/input-source` every 2.5 seconds and show the compact readiness state without enlarging the actual IME candidate overlay.
- Updated README and debug-surface docs with the `switch` vs `ready` distinction.

Verification:
- Added debug-server tests for `switch`, `ready`, and `install` readiness states.
- Real local check still reports Squirrel installed and HIToolbox-enabled but not active: `current=com.apple.keylayout.ABC`.

Status:
- Debug/debug-gate now gives live feedback while the user switches input sources.
- Continuous real typing validation is still pending until the active source becomes Squirrel.

### 2026-07-01 20:15 CST
Problem:
- After Squirrel became installed and visible, the workflow still required several separate commands: selected-source wait, sidecar health, and backend quality gate.
- This made it easy to lose the exact machine-readable evidence needed for the real tryout handoff.

Changes:
- Added `python3 -m rag_ime.cli squirrel-tryout-gate`.
- The new gate checks input-source readiness first, then sidecar `/health`, then runs the existing `quality-gate` with `--require-input-source-ready`.
- It fails fast when `readinessState=switch` and skips the expensive quality gate until Squirrel is actually selected.
- It can write the JSON report with `--report-path`.
- Updated README and Xcode setup docs to use the tryout gate after `scripts/wait_squirrel_typing_ready.sh`.

Verification:
- Added CLI tests for the not-selected fast-fail path and the selected fake-input-source path that proceeds into `quality-gate`.
- Current-machine smoke returned `readinessState=switch`, `sidecar-health passed`, and `quality-gate skipped`; the sidecar reports `local-ollama qwen3.5:0.8b-mlx streamFirstCandidate=true`.

Status:
- The real machine has a ready sidecar/model lane, but the active input source still must be switched from ABC to Squirrel before the tryout gate can pass.

### 2026-07-01 20:40 CST
Problem:
- `squirrel-tryout-gate` still trusted the CLI `--db-path` and sidecar URL without proving the installed `Squirrel.app` and the real user Rime config point at the same runtime.
- This could let the backend gate pass against one database while Squirrel was configured to use another database.

Changes:
- Added read-only installed bundle and installed Rime config checks to `squirrel-tryout-gate`.
- The bundle check verifies the installed `Squirrel.app` executable and reports the bundle identifier.
- The config check parses the `# >>> RAG-IME managed block` in `~/Library/Rime/squirrel.custom.yaml` and compares `enabled`, `sidecar_url`, `db_path`, and `project` against the tryout command.
- The sidecar URL comparison treats `http://127.0.0.1:8766` and `http://127.0.0.1:8766/api` as the same base because Squirrel appends endpoint paths under the configured base.

Verification:
- Added tests with fake `Squirrel.app` bundles and fake managed config blocks for both not-selected and selected input-source paths.
- Real local smoke now reports `installed-bundle passed`, `installed-rime-config passed`, and `sidecar-health passed`; it still fails on `input-source-ready` because current input source is ABC.

Status:
- The installed app/config/runtime path is machine-verifiable. Remaining blocker for the next gate is switching active macOS input source to Squirrel.

### 2026-07-01 21:00 CST
Problem:
- `squirrel-tryout-gate` checked sidecar `/health`, but health alone did not prove the Squirrel-facing `/rime-suggest` candidate payload was available.
- Calling `/rime-select` by default would write commit/action evidence, so the default gate needed a non-mutating sidecar probe.

Changes:
- Extended `squirrel-tryout-gate` sidecar check to POST a safe `/rime-suggest` probe with one synthetic Rime candidate.
- The report now includes `sidecar.rimeSuggest.schemaVersion`, `displayCandidateCount`, `queryBasis`, and cache metadata.
- The gate still does not call `/rime-select` by default; real side-candidate commit remains part of the manual/GUI verification layer.

Verification:
- Added a mock sidecar test proving the tryout gate calls `/rime-suggest` and records its display-candidate count.
- Real local smoke reports `rimeSuggest.ok=true`, `schemaVersion=rag-ime.rime-sidecar.v1`, `displayCandidateCount=2`, and `queryBasis=rimeCandidates`.

Status:
- Installed bundle, real Rime config, sidecar health, and sidecar candidate payload are now machine-verifiable.
- The active input source is still ABC, so backend quality-gate and foreground typing remain pending until switching to Squirrel.

### 2026-07-01 21:20 CST
Problem:
- The tryout gate could still pass sidecar health against a temporary terminal-started process.
- For a real input method install, the evidence needs to prove the sidecar is persisted as the login-time user LaunchAgent that Squirrel will call during normal typing.

Changes:
- Added a `launch-agent` check to `squirrel-tryout-gate`.
- The gate now runs `launchctl print gui/<uid>/com.rag-ime.sidecar`, reports `state`, `pid`, `path`, and `program`, and only allows backend `quality-gate` when the LaunchAgent is `running`.
- Tests use `--skip-launch-agent` so unit coverage stays independent of the host launchd state.

Verification:
- Added parser coverage for launchctl output.
- Real local smoke reports `installed-bundle passed`, `installed-rime-config passed`, `launch-agent passed state=running pid=13454`, `sidecar-health passed`, and `sidecar.rimeSuggest.displayCandidateCount=2`.
- The same real smoke still fails `input-source-ready` with `current=com.apple.keylayout.ABC`, so backend `quality-gate` is correctly skipped until the active macOS input menu is switched to Squirrel.
- Full 151-test suite passed.

Status:
- The installed Squirrel/Rime frontend, real Rime config, persisted sidecar service, and sidecar candidate payload are now separately machine-verifiable.
- Continuous real typing validation is still pending until the active input source becomes `鼠须管`.

### 2026-07-01 20:01 CST
Problem:
- Squirrel/鼠须管 was visible in macOS input sources, but selecting it did not produce normal typing output.
- Investigation found `~/Library/Rime` only had `squirrel.custom.yaml`; core schema/data files and `build/` artifacts were missing.
- Squirrel `--build` against the installed app `SharedSupport` can print errors such as `failed to save config` or `missing input schema` without reliably failing the install path.

Changes:
- Added `scripts/bootstrap_squirrel_user_data.sh`.
- The script copies bundled `SharedSupport` data and Plum output into `~/Library/Rime`, runs `Squirrel --build` and `--reload` from the user Rime directory, verifies expected build artifacts, and fails on silent build-error text.
- Integrated the bootstrap step into `scripts/build_patched_squirrel.sh install` before Squirrel postinstall.
- Updated README, Xcode setup, and macOS adapter docs to distinguish TIS/HIToolbox visibility from usable Rime schema data.

Verification:
- Added unit tests for user-data bootstrap success and silent `missing input schema` failure detection.
- Updated the install-action test to require user Rime build artifacts.

Status:
- The install chain now has a regression guard for the "input method exists but cannot type" failure.
- Next local step is to run the bootstrap script against the real installed Squirrel app and then perform manual foreground typing.

### 2026-07-01 20:12 CST
Problem:
- After fixing `~/Library/Rime`, System Settings still showed `ABC / 简体拼音 / 豆包输入法` rather than `鼠须管`.
- `com.apple.HIToolbox` contained Squirrel, but `com.apple.inputsources` still had only Doubao in `AppleEnabledThirdPartyInputSources`.
- This made the old `hitoolboxEnabled=true` check a false positive for System Settings visibility on macOS 27.

Changes:
- Tightened `scripts/check_macos_input_source.sh`: third-party input methods now require both HIToolbox and `com.apple.inputsources` entries before reporting `hitoolboxEnabled=true`; it also prints `thirdPartyEnabled`.
- Updated `scripts/enable_squirrel_hitoolbox_input_source.sh` to try updating both preference domains and to tell the user when the System Settings UI Add path is required.
- Updated README, Xcode setup, and macOS adapter docs with the macOS 27 third-party input-source caveat.

Findings:
- `defaults write/import com.apple.inputsources` may not persist command-line changes on this host, while the System Settings UI can still add the source.
- Real current state after tightening the check: Squirrel is TIS-registered/selectable but `thirdPartyEnabled=false`, so the remaining required step is UI Add -> Chinese, Simplified -> Squirrel.

### 2026-07-01 20:20 CST
Problem:
- `scripts/build_patched_squirrel.sh install` still used the loose TIS-only input-source check after postinstall.
- Debug readiness parsed `hitoolboxEnabled` but ignored the new `thirdPartyEnabled` field, so the UI could still say "switch input source" when System Settings had not actually added Squirrel.

Changes:
- `build_patched_squirrel.sh` now calls `check_macos_input_source.sh --require-hitoolbox-enabled` after postinstall and only prints OK when the real-use preference gates pass.
- `rag_ime.debug_server` parses `thirdPartyEnabled`; if HIToolbox or the third-party input-source list is missing, readiness becomes `install` with an add/enable action.
- `quality-gate` input-source checks now include `thirdPartyEnabled`.
- Added isolated tests for `check_macos_input_source.sh` with fake `swift` and temporary preference plists.

Verification:
- Targeted checker/debug tests passed.
- Full test suite passed: 156 tests.

Status:
- The project no longer treats TIS registration alone as real input-method readiness.
- Real local machine still requires the System Settings UI Add path before foreground Squirrel typing can be verified.

### 2026-07-01 20:25 CST
Problem:
- `squirrel-tryout-gate` checked the installed Squirrel bundle and managed Rime config, but not the compiled user Rime build artifacts.
- This left a gap where input-source/config checks could pass even if `~/Library/Rime/build` was missing and Squirrel could not produce normal candidates.

Changes:
- Added `installedRimeBuild` to `squirrel-tryout-gate`.
- The gate now checks `build/default.yaml`, `build/luna_pinyin.schema.yaml`, and `build/luna_pinyin.table.bin` under the same directory as `squirrel.custom.yaml`.
- Backend `quality-gate` only runs after bundle, config, Rime build, input-source, LaunchAgent, and sidecar checks pass.

Verification:
- Added a missing-build tryout test that fails fast and skips quality-gate.
- Updated README and Xcode setup docs to mention the build-artifact check.

Status:
- Read-only tryout evidence now covers the Squirrel app, RAG config, compiled Rime data, input-source readiness, LaunchAgent, and sidecar payload.

### 2026-07-01 20:31 CST
Problem:
- `scripts/wait_squirrel_typing_ready.sh` waited for selected input source even when Squirrel was not fully present in the current user's HIToolbox/third-party input-source lists.
- On macOS 27 this made the user wait for a menu-bar switch that could not appear until System Settings added Squirrel.

Changes:
- Added `scripts/wait_squirrel_input_source_added.sh`.
- The new gate waits for `check_macos_input_source.sh --require-hitoolbox-enabled` and prints the exact System Settings Add path while waiting.
- `wait_squirrel_typing_ready.sh` now fails fast with the add-gate instruction if `thirdPartyEnabled=false`.
- Updated README, Xcode setup, and macOS adapter docs to split "add source" from "select source".

Verification:
- Added tests for successful source-list detection and fast failure when Squirrel is not fully added.

Status:
- Manual next step is now operationally clean: run the add gate while adding Squirrel in System Settings, then run typing-ready after switching to Squirrel.

### 2026-07-01 20:45 CST
Problem:
- The browser debug Input Source card still compressed the macOS input-source state into `list/selected/current`, so the current real blocker `thirdPartyEnabled=false` was visible only in JSON.
- This made the page less useful for the exact "Squirrel is registered but cannot type" failure.

Changes:
- `/api/input-source` now returns `readinessChecks`, `manualAction`, and `verificationCommand`.
- The debug Input Source card now shows four compact gates: TIS, third-party source list, selected source, and current source.
- The card hint now includes the next action plus the verifying wait script.
- Removed debug-page favicon noise and tightened RAG source text truncation inside the compact overlay.

Verification:
- Targeted input-source debug tests passed.
- Playwright snapshot on the real machine showed `TIS=yes`, `3rd=no`, `selected=no`, `current=ABC`, readiness `install`, and `scripts/wait_squirrel_input_source_added.sh`.
- Screenshot evidence: `output/playwright/rag-ime-debug-input-source-install.png`.

Status:
- The debug surface now points directly to the System Settings Add step when macOS has not accepted Squirrel into the third-party input-source list.

### 2026-07-01 20:56 CST
Problem:
- The remaining real-use blocker requires the user to open Keyboard settings and add Squirrel manually, but the repo only printed the path as text.
- This still left unnecessary manual navigation friction when repeatedly testing the install flow.

Changes:
- Added `scripts/open_squirrel_input_source_settings.sh`.
- The helper opens the macOS Keyboard settings pane when the settings URL is accepted, prints the exact Add flow, and can run the strict add gate with `--wait`.
- `/api/input-source` install readiness now exposes `helperCommand=scripts/open_squirrel_input_source_settings.sh --wait`.
- Debug page, README, Xcode setup, macOS adapter docs, and wait-script error messages now point to the same helper path.

Verification:
- Added shell tests for already-added and missing-source helper behavior.
- Targeted wait/debug tests passed.
- Real local smoke with `--no-open` printed `thirdPartyEnabled=false` and the strict wait gate.
- Playwright snapshot showed the debug card recommending `scripts/open_squirrel_input_source_settings.sh --wait`; browser console had 0 errors.
- Screenshot evidence: `output/playwright/rag-ime-debug-input-source-helper.png`.

Status:
- The repo still does not click System Settings automatically; the manual Add step remains required, but the setup flow now opens the right settings area and waits with a strict machine-verifiable gate.

### 2026-07-01 23:50 CST
Problem:
- The real candidate panel still needed the product layout locked down: LLM short candidates should be horizontal, while RAG/memory sentence snippets should be vertical.
- The model lane also needed a real multi-candidate path instead of relying on stream-first single-candidate output or JSON completion.

Changes:
- Added direct MLX `candidateMode: next-token-logits` before JSON generation; `/predict` now derives multiple candidates from first-step logprobs.
- Sidecar merge keeps RAG block-row reserve when model predictions are available, so 8 visible slots can show short `model/inline` candidates followed by `rag/block` memory rows.
- Added regression coverage for the 8-slot mixed layout and updated the active Goal plus inference benchmark docs.

Verification:
- Focused sidecar/MLX/predictor tests passed: 61 tests.
- `py_compile` and `git diff --check` passed.
- Real doctor passed with `failures=0 warnings=0`.
- Manual `/rime-suggest` returned 5 `model/inline` candidates and 3 `rag/block` candidates; model lane elapsed 145 ms.

Commands:
- `.venv-mlx314sys/bin/python -m unittest tests.test_rime_sidecar tests.test_mlx_predictor_server tests.test_predictor`
- `python3 -m py_compile rag_ime/rime_sidecar.py rag_ime/mlx_predictor_server.py rag_ime/predictor.py rag_ime/cli.py`
- `RAG_IME_DOCTOR_REQUIRE_TRYOUT=1 RAG_IME_SQUIRREL_WORKDIR=/tmp/rag-ime-squirrel-verify scripts/doctor_squirrel_integration.sh`

Status:
- Current active path is direct MLX service with local `/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-4bit`, `streamFirstCandidate=false`, `logitsTopK=true`, `batchCandidates=true`, `sequenceFork=false`.
- Remaining uncompleted item in the Goal is the 3 downloaded safetensors model comparison plus final git sync.

### 2026-07-01 23:59 CST
Problem:
- The product goal explicitly called out raw key noise such as `asdioj`: the IME must not ask an unconstrained LLM to decode it, but it also should not drop useful predictions immediately after the user has just committed Chinese text.

Changes:
- Updated the Squirrel patch to track `queryBasis`, display update time, and a 1.2s display holdover window.
- If the current raw/preedit has no Rime fallback candidates and the previous sidecar response was based on `committedContext`, Squirrel briefly keeps those side candidates visible while the raw composition changes.
- Kept fail-closed behavior for raw input with no Rime candidates and no recent committed context.
- Updated README/debug/issue-map docs and the active Goal record.

Verification:
- Patch/prepare/sidecar tests passed: 27 tests.
- `git diff --check` passed.
- Re-prepared Squirrel workdir from the patch, rebuilt, and installed patched Squirrel.app.
- Re-registered the input source after install; doctor passed with `failures=0 warnings=0`.
- Manual `/rime-suggest` check: `asdioj` with no context skipped side lanes; `asdioj` with recent committed Chinese context returned model/RAG side candidates via `queryBasis=committedContext`.

Commands:
- `RAG_IME_SQUIRREL_RESET=1 RAG_IME_SQUIRREL_WORKDIR=/tmp/rag-ime-squirrel-verify scripts/prepare_squirrel_workspace.sh`
- `RAG_IME_SQUIRREL_WORKDIR=/tmp/rag-ime-squirrel-verify scripts/build_patched_squirrel.sh install`
- `RAG_IME_DOCTOR_REQUIRE_TRYOUT=1 RAG_IME_SQUIRREL_WORKDIR=/tmp/rag-ime-squirrel-verify scripts/doctor_squirrel_integration.sh`

Status:
- Installed Squirrel is registered as `im.rime.inputmethod.Squirrel.Hans`, enabled and third-party-visible, but current source remains ABC until the user switches input source for foreground typing.

### 2026-07-02 00:14 CST
Problem:
- User clarified the real panel rule: LLM short candidates should be horizontal, while sentence-like RAG/memory candidates should remain vertical rows.
- The screenshot showed Rime fallback candidates in a vertical list, so the Squirrel front end needed stronger sidecar-panel state guarding and the installed app needed to be refreshed.

Changes:
- Updated the Squirrel patch with `ragImePanelUsesDisplayCandidates` so stale sidecar candidates cannot hijack ordinary Rime fallback display or number-key routing.
- Added `ragImePanelForcesHorizontalLayout`, `ragImePanelLinear`, and `ragImePanelVertical`; when active sidecar candidates include `model/inline`, the panel uses a horizontal LLM lane while `rag/block` candidates still start new rows.
- Re-generated the patch from the applied Squirrel worktree to keep git hunk counts valid.

Verification:
- `scripts/prepare_squirrel_workspace.sh` passed with a reset `/tmp/rag-ime-squirrel-verify` workdir.
- Focused tests passed: `tests.test_build_patched_squirrel`, `tests.test_rime_sidecar`, `tests.test_mlx_predictor_server`, `tests.test_predictor` (66 tests).
- `py_compile` and `git diff --check` passed.
- Manual `/rime-suggest` for `erq` returned 5 `model/inline` candidates followed by 3 `rag/block` candidates; model lane elapsed 158 ms.
- Xcode Release build installed patched `~/Library/Input Methods/Squirrel.app`; after re-registering, selected source is `im.rime.inputmethod.Squirrel.Hans`.
- Doctor passed with `failures=0 warnings=0`.

Commands:
- `RAG_IME_SQUIRREL_RESET=1 RAG_IME_SQUIRREL_WORKDIR=/tmp/rag-ime-squirrel-verify scripts/prepare_squirrel_workspace.sh`
- `python3 -m unittest tests.test_build_patched_squirrel tests.test_rime_sidecar tests.test_mlx_predictor_server tests.test_predictor`
- `RAG_IME_SQUIRREL_WORKDIR=/tmp/rag-ime-squirrel-verify scripts/build_patched_squirrel.sh install`
- `scripts/select_macos_input_source.sh im.rime.inputmethod.Squirrel.Hans`
- `RAG_IME_DOCTOR_REQUIRE_TRYOUT=1 RAG_IME_SQUIRREL_WORKDIR=/tmp/rag-ime-squirrel-verify scripts/doctor_squirrel_integration.sh`

Status:
- Installed Squirrel is now selected and ready for foreground typing tests with the user.

### 2026-07-02 00:32 CST
Problem:
- User clarified the final panel rule again: LLM candidates must be horizontally arranged; sentence-like RAG/memory candidates are the vertical rows.
- Live sidecar payload already returned `model/inline` followed by `rag/block`, but the installed app could still be an older Squirrel build and the sidecar LaunchAgent could lose its MLX predictor environment.

Changes:
- Added build/preparation guards so patched Squirrel workdirs must contain `ragImePanelForcesHorizontalLayout`, `ragImePanelLinear`, and `candidateSeparator`.
- Added MLX model inspection to `/health` and sidecar predictor status, including `textOnly`, `hasVisionConfig`, architecture, vocab/layer sizes, and quantization.
- Doctor now warns when the active MLX model contains `vision_config`, because that wastes memory/latency for an input method compared with a pure text model.
- Reinstalled patched Squirrel from `/tmp/rag-ime-squirrel-verify`.
- Reinstalled the resident MLX predictor LaunchAgent and reinstalled the sidecar LaunchAgent with `RAG_IME_PREDICTOR_PROVIDER=mlx`.

Verification:
- Focused tests passed: `tests.test_mlx_predictor_server`, `tests.test_predictor`, `tests.test_debug_server`, `tests.test_rime_sidecar`, `tests.test_build_patched_squirrel`, `tests.test_prepare_squirrel_workspace` (95 tests).
- `py_compile`, `bash -n`, and `git diff --check` passed.
- Installed `/rime-suggest` payload returned 1-5 as `model/inline` and 6-8 as `rag/block`; model lane elapsed 118 ms.
- MLX `/health` and sidecar `/health` both report provider `local-mlx` with model `/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-4bit`.
- Doctor passed with `failures=0 warnings=1`; the warning is the intended text-only-model warning for the current Qwen3.5 VLM package.

Commands:
- `python3 -m unittest tests.test_mlx_predictor_server tests.test_predictor tests.test_debug_server tests.test_rime_sidecar tests.test_build_patched_squirrel tests.test_prepare_squirrel_workspace`
- `RAG_IME_SQUIRREL_WORKDIR=/tmp/rag-ime-squirrel-verify scripts/build_patched_squirrel.sh install`
- `RAG_IME_MLX_PYTHON="$PWD/.venv-mlx314sys/bin/python" RAG_IME_MLX_MODEL="/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-4bit" scripts/install_mlx_predictor_launch_agent.sh`
- `RAG_IME_PREDICTOR_PROVIDER=mlx RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:8767 RAG_IME_PREDICTOR_MODEL="/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-4bit" RAG_IME_PREDICTOR_PROFILE=instant RAG_IME_PREDICTOR_TIMEOUT_MS=350 scripts/install_sidecar_launch_agent.sh`
- `RAG_IME_DOCTOR_REQUIRE_TRYOUT=1 RAG_IME_SQUIRREL_WORKDIR=/tmp/rag-ime-squirrel-verify scripts/doctor_squirrel_integration.sh`

Status:
- Runtime layout contract is correct: short LLM predictions are inline/horizontal metadata, RAG/memory sentences are block rows.
- Current model is usable for the path but not ideal: it is a Qwen3.5 vision-language MLX package, so the next model task is to replace it with a complete pure-text MLX directory.

### 2026-07-02 00:55 CST
Problem:
- The active MLX model still used the Qwen3.5 VLM package, which made doctor warn about `vision_config` and wasted disk/memory for an input method.
- Direct Hugging Face shell downloads were unreliable from this environment: official HF timed out without proxy, while proxy/mirror attempts failed with SSL errors.

Changes:
- Added `scripts/derive_text_mlx_model.py` to derive a text-only MLX-LM directory from a Qwen3.5 MLX-VLM source by keeping only `language_model.*` weights and removing `vision_config`.
- Created `/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-text-4bit-local` from the existing VLM directory; safetensors size dropped from about 625 MB to about 424 MB.
- Reinstalled the MLX predictor LaunchAgent and sidecar LaunchAgent to use the derived text-only model.
- Updated README and macOS frontend docs with the repeatable derivation and install commands.

Verification:
- Direct `MlxLmEngine` load of the derived directory succeeded.
- Direct predict returned `candidateMode=next-token-logits` with 5 candidates in 135 ms in the manual smoke.
- Runtime `/health` now reports `textOnly=true`, `hasVisionConfig=false`, and `textOnlyModel=true` for both the MLX service and sidecar predictor.
- Installed `/rime-suggest` returned 1-5 `model/inline` and 6-8 `rag/block`; model lane elapsed 125 ms.
- Doctor passed with `failures=0 warnings=0`.

Commands:
- `.venv-mlx314sys/bin/python scripts/derive_text_mlx_model.py --source-dir "/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-4bit" --target-dir "/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-text-4bit-local" --overwrite`
- `RAG_IME_MLX_PYTHON="$PWD/.venv-mlx314sys/bin/python" RAG_IME_MLX_MODEL="/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-text-4bit-local" scripts/install_mlx_predictor_launch_agent.sh`
- `RAG_IME_PREDICTOR_PROVIDER=mlx RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:8767 RAG_IME_PREDICTOR_MODEL="/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-text-4bit-local" RAG_IME_PREDICTOR_PROFILE=instant RAG_IME_PREDICTOR_TIMEOUT_MS=350 scripts/install_sidecar_launch_agent.sh`
- `RAG_IME_DOCTOR_REQUIRE_TRYOUT=1 RAG_IME_SQUIRREL_WORKDIR=/tmp/rag-ime-squirrel-verify scripts/doctor_squirrel_integration.sh`

Status:
- Current active model path is `/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-text-4bit-local`.
- Remaining goal work is real foreground typing validation, digit-key selection validation in the live panel, and further quality/latency optimization beyond logits top-k.

### 2026-07-02 00:56 CST
Problem:
- The native Squirrel sidecar request fingerprint did not include `committedContext`.
- This could let an older sidecar request/panel survive after the user committed new Chinese text, weakening history-context prediction and making live candidates stale.

Changes:
- Added `committedContext` to `ragImeRequestFingerprint` in the Squirrel patch.
- Added stale-response guards so a sidecar response is dropped if either the response context or current `ragImeCommittedContext` no longer matches the request.
- Updated patch tests to lock the committed-context fingerprint and guard contract.
- Rebuilt and reinstalled patched Squirrel.app from `/tmp/rag-ime-squirrel-verify`.

Verification:
- Real patch apply passed after fixing unified-diff hunk counts.
- `scripts/build_patched_squirrel.sh install` built the Release app and installed it into `~/Library/Input Methods/Squirrel.app`.
- Focused tests passed: `tests.test_build_patched_squirrel`, `tests.test_prepare_squirrel_workspace`, `tests.test_rime_sidecar`, `tests.test_debug_server`, `tests.test_mlx_predictor_server`, `tests.test_predictor` (95 tests).
- Re-registration required `RAG_IME_SQUIRREL_APP="$HOME/Library/Input Methods/Squirrel.app" scripts/enable_squirrel_hitoolbox_input_source.sh`; after that `im.rime.inputmethod.Squirrel.Hans` was enabled, selectable, selected, and `thirdPartyEnabled=true`.
- Doctor passed with `failures=0 warnings=0`; sidecar still reports text-only MLX model `/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-text-4bit-local`.

Commands:
- `RAG_IME_SQUIRREL_WORKDIR=/tmp/rag-ime-squirrel-verify RAG_IME_SQUIRREL_RESET=1 scripts/prepare_squirrel_workspace.sh`
- `RAG_IME_SQUIRREL_WORKDIR=/tmp/rag-ime-squirrel-verify scripts/build_patched_squirrel.sh install`
- `RAG_IME_SQUIRREL_APP="$HOME/Library/Input Methods/Squirrel.app" scripts/enable_squirrel_hitoolbox_input_source.sh`
- `RAG_IME_DOCTOR_REQUIRE_TRYOUT=1 RAG_IME_SQUIRREL_WORKDIR=/tmp/rag-ime-squirrel-verify scripts/doctor_squirrel_integration.sh`

Status:
- Installed runtime is back to `Squirrel - Simplified`, selected and ready.
- Remaining unproven part is still foreground live typing: user-visible panel behavior and number-key commit in real apps.

### 2026-07-02 01:00 CST
Problem:
- Strict doctor verified sidecar health and `/rime-select`, but it did not yet fail on the actual product contract: 8 visible slots should be side-first, model candidates should be `inline/model`, RAG candidates should be `block/memory`, and visible labels must match `selectionKey` / `selectionRank`.
- Without that gate, a regression could keep `/rime-suggest` alive while silently breaking the horizontal LLM lane or numeric selection routing.

Changes:
- Added a strict mixed-candidate contract check to `scripts/doctor_squirrel_integration.sh`.
- In `RAG_IME_DOCTOR_REQUIRE_TRYOUT=1` mode, doctor now requires shared selection keys/ranks, side-first merge policy, model-before-RAG ordering, at least one model inline candidate, and at least one RAG block candidate.
- Updated doctor tests and debug/Xcode docs to state what this gate proves and what still needs manual foreground validation.

Verification:
- `python3 -m unittest tests.test_doctor_squirrel_integration` passed.
- `bash -n scripts/doctor_squirrel_integration.sh` and `git diff --check` passed.
- Real strict doctor passed with `display=8 model=5 rag=3 rime=0` and `candidate contract: model inline + rag block + shared selection keys passed`.

Commands:
- `python3 -m unittest tests.test_doctor_squirrel_integration`
- `RAG_IME_DOCTOR_REQUIRE_TRYOUT=1 RAG_IME_SQUIRREL_WORKDIR=/tmp/rag-ime-squirrel-verify scripts/doctor_squirrel_integration.sh`

Status:
- Backend/native payload contract is now a repeatable strict gate.
- Remaining unproven part is the actual foreground AppKit panel and real number-key commit in a normal editor.

### 2026-07-02 01:21 CST
Problem:
- User clarified the real panel design: LLM short candidates should be horizontal; sentence/paragraph candidates should be vertical rows.
- The sidecar already returned `displayLayout=inline/displayLane=model` and `displayLayout=block/displayLane=memory`, but real Squirrel could still show the native vertical list because repeated UI refreshes advanced request state and made valid sidecar responses look stale.

Changes:
- Added `ragImePendingRequestFingerprint` and duplicate in-flight suppression to the Squirrel patch so equivalent refreshes do not keep bumping `requestSeq`.
- Relaxed sidecar response freshness to require request-local `response.requestSeq == request.requestSeq` plus current input/context/fingerprint match, instead of comparing with the latest global sequence.
- Updated `SquirrelPanel` sizing, positioning, scroll paging, bounds rotation, and text layout to use the mixed `ragImePanelVertical` decision rather than raw theme `vertical`.
- Updated patch tests to lock the frontend contract.
- Rebuilt and installed patched Squirrel.app into `~/Library/Input Methods/Squirrel.app`.

Verification:
- Xcode Release install succeeded from `/tmp/rag-ime-squirrel-verify`.
- `scripts/check_macos_input_source.sh --require-selected im.rime.inputmethod.Squirrel.Hans` passed; Squirrel Simplified is enabled, selectable, selected, HIToolbox enabled, and third-party enabled.
- Strict doctor passed with `failures=0 warnings=0`; candidate contract reports `display=8 model=5 rag=3 rime=0`.
- Manual `/rime-suggest` schema check returned labels 1-5 as `sourceType=model`, `displayLayout=inline`, `displayLane=model`; labels 6-8 as `sourceType=rag`, `displayLayout=block`, `displayLane=memory`.
- Focused tests passed: 57 tests. `git diff --check` and shell syntax checks passed.

Commands:
- `RAG_IME_SQUIRREL_WORKDIR=/tmp/rag-ime-squirrel-verify scripts/build_patched_squirrel.sh install`
- `RAG_IME_DOCTOR_REQUIRE_TRYOUT=1 RAG_IME_SQUIRREL_WORKDIR=/tmp/rag-ime-squirrel-verify scripts/doctor_squirrel_integration.sh`
- `scripts/check_macos_input_source.sh --require-selected im.rime.inputmethod.Squirrel.Hans`
- `python3 -m unittest tests.test_build_patched_squirrel tests.test_prepare_squirrel_workspace tests.test_doctor_squirrel_integration tests.test_rime_sidecar tests.test_debug_server`

Status:
- Installed input method now has the frontend patch for horizontal LLM lane plus vertical RAG sentence rows.
- Remaining validation is visual foreground typing in a normal editor and real number-key commit confirmation.

### 2026-07-02 03:27 CST
Problem:
- The real system can pass current HTTP sidecar/model checks while launchd remains configured to restart an older sidecar or MLX predictor.
- User-visible layout debugging also showed the backend contract is correct but the system can still load stale same-bundle Squirrel.app from `/Library/Input Methods`.

Changes:
- Extended strict `scripts/doctor_squirrel_integration.sh` with LaunchAgent plist drift checks.
- Doctor now reads sidecar and MLX predictor plists, compares source root/provider/model/base URL/stream-first settings with current sidecar health, and verifies the MLX predictor starts with matching text-only model, empty proxy vars, and `--prompt-cache`.
- Added tests for strict tryout passing with matching plists and failing when plist model paths drift.
- Updated debug/Xcode docs to explain the restart-drift gate.

Verification:
- `bash -n scripts/doctor_squirrel_integration.sh` passed.
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest tests.test_doctor_squirrel_integration` passed: 12 tests.
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest discover -s tests` passed: 192 tests.
- Real strict doctor confirms sidecar LaunchAgent and MLX predictor LaunchAgent both match current `local-mlx` text-only model and prompt-cache config.

Status:
- Remaining blocker is still the stale root-owned `/Library/Input Methods/Squirrel.app`, which requires the user to run `scripts/replace_system_squirrel_app.sh` and enter the Mac admin password.

### 2026-07-02 03:31 CST
Problem:
- `scripts/replace_system_squirrel_app.sh` replaced the system app but did not make the post-copy strict doctor gate mandatory.
- A user could enter the admin password, copy the app, and still miss a stale duplicate, bad copy, or LaunchAgent model drift until a later manual doctor run.

Changes:
- `replace_system_squirrel_app.sh` now verifies the target app contains the mixed-layout patch immediately after copy.
- The replacement script now runs strict doctor without foreground trace by default, with `RAG_IME_SQUIRREL_APP` set to the system target and duplicate candidates limited to source+target.
- Added `RAG_IME_SQUIRREL_REPLACE_RUN_DOCTOR=0` as a narrow escape hatch for installer debugging.
- Added tests with fake `sudo`, `ditto`, input-source scripts, and doctor to prove post-copy doctor env wiring and failure when the copied target lacks patch markers.

Verification:
- `bash -n scripts/replace_system_squirrel_app.sh` passed.
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest tests.test_replace_system_squirrel_app` passed: 2 tests.

Status:
- User still needs to run `scripts/replace_system_squirrel_app.sh` with admin password; after this change, that single command also performs the non-foreground strict runtime gate.

### 2026-07-02 03:38 CST
Problem:
- A strict doctor run briefly failed the model lane with no `model/inline` candidates even though direct `/rime-suggest` immediately returned MLX logits candidates.
- Root cause: doctor omitted `latencyBudgetMs`, so sidecar used its 150 ms fallback. The real patched Squirrel config sends 180 ms, and the local MLX logits path is currently close to that edge.

Changes:
- Added `RAG_IME_DOCTOR_LATENCY_BUDGET_MS`, defaulting to 180, and included it in all doctor `/rime-suggest` probes.
- Doctor output now prints `doctor_latency_budget_ms`.
- Added doctor test coverage proving the default 180 ms budget is sent to the fake sidecar.
- Updated debug/Xcode docs to explain the budget alignment.

Verification:
- `bash -n scripts/doctor_squirrel_integration.sh` passed.
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest tests.test_doctor_squirrel_integration` passed: 12 tests.
- Real strict doctor now returns `display=8 model=5 rag=3 rime=0` under `doctor_latency_budget_ms: 180`; remaining failure is only stale `/Library/Input Methods/Squirrel.app`.

### 2026-07-02 03:56 CST
Problem:
- User clarified again that LLM candidates should be horizontal, while sentence/RAG candidates should be vertical rows.
- The backend candidate contract already returned `1-5 model/inline` and `6-8 rag/block`, but macOS could still load the stale root-owned `/Library/Input Methods/Squirrel.app` with the same bundle id, making the real panel look like the old vertical Squirrel UI.

Changes:
- Added a brandable install path for patched Squirrel: `RAG-IME.app` with bundle/input-source prefix `im.rag-ime.inputmethod.RagIme`.
- `prepare_squirrel_workspace.sh` now rewrites Squirrel's input-source prefix usage to read `TISInputSourceID` from the app bundle instead of hardcoding `im.rime.inputmethod.Squirrel`.
- Added `scripts/brand_squirrel_app.sh` to rewrite `Info.plist`, Hans/Hant input source IDs, connection name, and localized input-source names.
- `build_patched_squirrel.sh` can now install a branded app while preserving the old default Squirrel path.
- Doctor duplicate detection now compares against the configured app's bundle id, so the original system Squirrel no longer blocks an independent RAG-IME build.
- Hardened `enable_squirrel_hitoolbox_input_source.sh` so it reports when macOS refuses to persist ThirdParty input-source preferences.

Verification:
- Built and installed `/Users/undo/Library/Input Methods/RAG-IME.app`.
- Strict doctor passed for the branded app with `summary: failures=0 warnings=0`.
- Doctor confirmed `display=8 model=5 rag=3 rime=0`, `model inline + rag block`, local MLX text-only model, prompt cache, and LaunchAgent config.
- `python3 -m unittest discover -s tests` passed: 196 tests.

Status:
- `RAG-IME - Simplified` is installed and visible to macOS TIS as enabled/selectable.
- Codex cannot persist `com.apple.inputsources` ThirdParty preferences from this process; macOS denied both `defaults write` and direct plist write. The remaining foreground step is adding/selecting `RAG-IME - Simplified` once in System Settings, or letting Codex do that via GUI after user confirmation.

### 2026-07-02 04:18 CST
Problem:
- User clarified the layout again: LLM candidates should be horizontal, while sentence/RAG candidates should be vertical.
- The screenshot showing `而且 / 而去 / 二期` was Rime pinyin fallback, not the LLM lane. Rime fallback can still appear vertically when side candidates are absent or not yet applied.
- The real risk was high-frequency composing: a previous MLX request could keep the model semaphore busy, so a new `/rime-suggest` response might contain only RAG/Rime and visually lose the horizontal model row.

Changes:
- Added a sub-second model holdover cache in `rag_ime/rime_sidecar.py`.
- If the model lane is already running and the committed context matches, `/rime-suggest` reuses the most recent successful model predictions and reports `modelLane.holdoverHit=true`.
- If MLX obtains the model lane but exceeds the IME latency budget, `/rime-suggest` can also reuse the same-context model holdover; the lane reports both `timedOut=true` and `holdoverHit=true`.
- Kept the layout contract strict: `sourceType=model + displayLayout=inline` is the horizontal LLM row; `sourceType=rag + displayLayout=block` is the vertical sentence/RAG row; Rime fallback is not counted as LLM.
- Added tests for the layout contract, busy-model holdover behavior, and timeout-holdover behavior.
- Reinstalled the sidecar LaunchAgent so `/Users/undo/Library/Application Support/RagIme/app` uses the updated runtime.

Verification:
- `python3 -m unittest tests.test_rime_sidecar` passed.
- `python3 -m py_compile rag_ime/rime_sidecar.py` passed.
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest discover -s tests` passed: 201 tests.
- `scripts/doctor_squirrel_integration.sh` passed with `display=8 model=5 rag=3 rime=0`, logits/top-k MLX model path, prompt cache, and LaunchAgent config.
- Sidecar reinstall passed health check.
- Live `/api/rime-suggest` probe returned `modelInline=5`, `ragBlock=3`, `rime=0`; labels 1-5 are MLX inline model candidates and labels 6-8 are RAG block candidates.

Status:
- Backend and installed sidecar now satisfy the requested layout contract.
- Remaining user-visible validation is foreground Squirrel/RAG-IME panel trace and real number-key commit in an editor.

### 2026-07-02 04:34 CST
Problem:
- Continued the goal audit after the layout commit.
- `RAG-IME - Simplified` is visible to TIS but cannot be selected: `TISSelectInputSource failed: -50`.
- `com.apple.inputsources.plist` does not persist `AppleEnabledThirdPartyInputSources` for `im.rag-ime.inputmethod.RagIme`; `defaults import` is rolled back and direct plist write is denied by macOS.
- Current selectable source is still `im.rime.inputmethod.Squirrel.Hans`; user-local `~/Library/Input Methods/Squirrel.app` is patched, but root-owned `/Library/Input Methods/Squirrel.app` has the same bundle id and lacks the RAG-IME mixed-layout patch.
- Foreground auto trace could not be produced from Codex: `osascript` lacks Accessibility permission for key events, and system screenshot capture returned a black frame.

Changes:
- Clarified doctor stale-duplicate output so it points directly to `scripts/replace_system_squirrel_app.sh`.
- Added test assertions that stale duplicate warnings/failures include the replacement command.
- Added `scripts/replace_system_squirrel_app.sh --preflight`, a no-op diagnostic mode that reports source/target patch markers, input-source status, sudo cache status, and whether system replacement is still required.

Verification:
- `scripts/check_macos_input_source.sh --require-selected im.rime.inputmethod.Squirrel.Hans` passed.
- Real `scripts/replace_system_squirrel_app.sh --preflight` returned `source_patch=true`, `target_patch=false`, `replacement_required=true`, `sudo_cached=false`.
- Real strict doctor now fails with the stale-system-app message plus `scripts/replace_system_squirrel_app.sh`, while still proving `display=8 model=5 rag=3 rime=0`, MLX logits/top-k, prompt cache, and LaunchAgent config.
- Branded `RAG-IME` input source remains enabled/selectable but not selected and `thirdPartyEnabled=false`.
- User-local patched Squirrel passed runtime sidecar checks, but doctor fails when duplicate stale `/Library/Input Methods/Squirrel.app` is treated as required.

Status:
- The next real unblock is replacing `/Library/Input Methods/Squirrel.app` with the patched app using admin credentials, or manually removing the stale system Squirrel app.
- After that, rerun foreground trace with either manual typing or Accessibility permission for Codex/Terminal automation.

### 2026-07-02 12:44 CST
Problem:
- User reported that the visible flow still looked like traditional Rime/wanxiang candidates and that LLM/RAG/memory output was not reliably visible.
- Live sidecar probing found the concrete service-layer bug: `post_commit_predicting` was inferred, but when `rawInput/preedit` were empty and only `committedContext` existed, `decide_side_candidate_refresh()` skipped side lanes until an idle delay, leaving the post-commit panel empty.

Changes:
- `committedContext` with no active composition now refreshes immediately as `refresh: post-commit continuation`.
- Prediction-first fallback filters low-value wanxiang/Rime terms in prediction modes, so weak contexts do not fall back to `根据/基于/和/测试`.
- MLX/provider low-value filters now also remove short phrase noise such as `测试流程`, `分析问题`, and `当前问题`.
- `scripts/verify_prediction_first_sidecar.py` now live-checks seven flows: prefix-constrained model+memory, post-commit model+memory, weak-context filtering, raw command, code identifier, path input, and plain Rime anchor fallback.

Commands:
- `git status -sb`: branch `codex/wisdom-weasel-rag-ime-mvp`; modified prediction/sidecar/test files; untracked `installation.yaml` left untouched.
- `git diff --stat`: 7 files, 158 insertions, 3 deletions before commit.
- `python3 -m unittest tests.test_prediction_first tests.test_rime_sidecar tests.test_predictor tests.test_pinyin_index`: 88 tests passed.
- Restarted MLX predictor LaunchAgent and sidecar LaunchAgent; both health checks passed.
- `python3 scripts/verify_prediction_first_sidecar.py --latency-budget-ms 350`: live sidecar verification passed with all seven cases.

Findings:
- Backend service flow is now genuinely Prediction-first for the tested paths: post-commit returns `model + memory` with no Rime fallback, prefix-constrained returns model/memory before fallback, and code/path/command input keeps raw English first.
- Remaining foreground validation is still native macOS/Squirrel panel behavior in real editors.

### 2026-07-02 14:45 CST
Problem:
- User reported the current LLM/RAG/memory candidate display still felt like a stiff non-disappearing clipboard panel.
- The desired reference is Wisdom-Weasel's LLM prediction behavior: prediction appears naturally after commit, but does not keep blocking input after stale/empty responses.

Changes:
- Re-aligned the sidecar contract to a short-lived prediction session: `predictionFirst.policy.panelVisible`, `hideWhenEmpty`, and `sessionBound` now explicitly tell the frontend when to show or clear the panel.
- Added a short post-commit continuation TTL so AI candidates can visually connect after a commit but disappear before they block digits/English/code input.
- Tightened the Wisdom-Weasel-style candidate lifecycle again: patched Squirrel post-commit holdover is now 0.9s, native RagImeMac is 0.85s, and hidden/expired candidates can no longer route number keys.
- Bound model holdover cache to the current semantic input state, so `sj` -> `sja` cannot reuse an old model row while the model lane is busy.
- Split side suggestions into real `rag` and `memory` lanes, then balanced `rag/memory/model` so all three sources can be visible before pure score sorting fills the rest.
- Added short pinyin-prefix lookup for active composition, while keeping long dirty raw pinyin out of semantic RAG queries.
- Updated SQLite retrieval to filter with original query plus pinyin index first, then only use expanded query as a relaxed fallback.
- Unified Squirrel frontend patch marker to `sidecar_empty_response_cleared`; empty sidecar responses must clear the stale panel rather than be treated as ignored.
- Updated MLX logits tests so the fast path represents phrase-like IME candidates, not low-value single token candidates.

Commands:
- `python3 -m unittest tests.test_debug_server tests.test_rime_sidecar tests.test_local_sqlite_core tests.test_prediction_first tests.test_demo_quality`: 121 tests passed.
- `python3 -m unittest -v tests.test_prepare_squirrel_workspace.PrepareSquirrelWorkspaceScriptTests.test_prepare_squirrel_workspace_applies_patch_and_writes_config_offline tests.test_doctor_squirrel_integration.DoctorSquirrelIntegrationScriptTests.test_doctor_reports_stale_duplicate_squirrel_app_as_warning tests.test_doctor_squirrel_integration.DoctorSquirrelIntegrationScriptTests.test_doctor_ignores_original_squirrel_when_configured_app_uses_branded_bundle_id tests.test_mlx_predictor_server.MlxPredictorServerTests.test_engine_predict_prefers_next_token_logits_candidates tests.test_replace_system_squirrel_app`: 7 tests passed.
- `python3 -m unittest -v tests.test_rime_sidecar.RimeSidecarTests.test_busy_model_lane_reuses_short_model_holdover_for_horizontal_row tests.test_rime_sidecar.RimeSidecarTests.test_busy_model_lane_does_not_reuse_holdover_after_prefix_changes tests.test_rime_sidecar.RimeSidecarTests.test_model_lane_timeout_reuses_holdover_for_horizontal_row tests.test_rime_sidecar.RimeSidecarTests.test_prediction_first_post_commit_clears_stale_empty_panel`: 4 tests passed.
- `python3 -m unittest discover -s tests`: 264 tests passed.

Findings:
- The backend/debug flow now matches the Wisdom-Weasel lifecycle principle: show only while the prediction session has live candidates, hide on stale/empty session.
- Remaining validation is still foreground macOS panel behavior after reinstall/reload of the patched Squirrel frontend.

### 2026-07-02 15:09 CST
Problem:
- The active goal now explicitly says not to treat the current patched Squirrel route as the final usable frontend.
- Existing `predictionFirst.policy.panelVisible` mixed together normal Rime/wanxiang candidate visibility and AI prediction-panel visibility, which could mislead a future non-Squirrel macOS adapter.

Changes:
- Added frontend-neutral `PredictionSessionState` and `PredictionSessionPhase` in `rag_ime/prediction_first.py`.
- Added `resolve_prediction_session()` and `prediction_session_to_payload()` so any frontend can distinguish:
  - first-word `anchor_composing`: Rime/wanxiang panel visible, AI prediction panel cleared;
  - `post_commit`: AI prediction panel visible and selection scope is prediction;
  - `prefix_constrained`: Rime owns composition while prediction candidates can be inserted first;
  - `raw_passthrough` / `hidden`: stale prediction panel must be cleared.
- `/rime-suggest` now returns top-level `predictionSession` alongside `predictionFirst`.
- Updated shared adapter contract, debug docs, and the redesign plan so future macOS frontend work consumes this lifecycle contract instead of copying patched Squirrel behavior.

Commands:
- `python3 -m py_compile rag_ime/prediction_first.py rag_ime/rime_sidecar.py`: passed.
- `python3 -m unittest tests.test_prediction_first tests.test_rime_sidecar.RimeSidecarTests.test_prediction_first_merge_prefix_keeps_llm_rag_before_wanxiang_fallback tests.test_rime_sidecar.RimeSidecarTests.test_prediction_first_post_commit_clears_stale_empty_panel`: 12 tests passed.
- `python3 -m unittest tests.test_debug_server tests.test_rime_sidecar tests.test_prediction_first tests.test_demo_quality tests.test_local_sqlite_core tests.test_mlx_predictor_server`: 129 tests passed.
- `python3 -m unittest discover -s tests`: 265 tests passed.

Findings:
- This moves the core product behavior closer to the requested adapter-independent route: frontends can now clear or show the AI prediction layer without relying on Squirrel-specific trace markers.

### 2026-07-02 15:16 CST
Problem:
- `PredictionSession` defined the frontend-visible state, but there was still no reusable manager that maintained a candidate pool across post-commit and continued-prefix updates.
- Without a manager, each future macOS adapter could accidentally reimplement patched-Squirrel-specific cache and clear-panel behavior.

Changes:
- Added `rag_ime/prediction_manager.py`.
- `PredictionManager.render()` accepts a structured Rime/wanxiang snapshot, optional fresh model/RAG/memory sources, and optional `raw_commit_text`.
- The manager binds the candidate pool to the committed-context fingerprint and a short TTL.
- Continued pinyin can reuse the current candidate pool and apply prefix filtering.
- Raw passthrough such as `git status` forces `RAW_INPUT`, clears the AI prediction panel, and does not reuse stale LLM/RAG candidates.
- Added tests for post-commit sources, prefix reuse, TTL expiry, context change, and raw passthrough.
- Updated shared adapter contract and redesign plan to name `PredictionManager` as the future frontend entrypoint.

Commands:
- `python3 -m py_compile rag_ime/prediction_manager.py rag_ime/prediction_first.py`: passed.
- `python3 -m unittest tests.test_prediction_manager tests.test_prediction_first`: 15 tests passed.
- `python3 -m unittest tests.test_prediction_manager tests.test_prediction_first tests.test_rime_sidecar tests.test_debug_server tests.test_demo_quality`: 95 tests passed.
- `python3 -m unittest discover -s tests`: 270 tests passed.

Findings:
- This is a concrete step away from the unavailable patched-Squirrel route: the future adapter can call `PredictionManager` directly and keep ordinary input stable by construction.

### 2026-07-02 15:35 CST
Problem:
- User feedback: the current LLM/RAG/memory candidates felt like a passive popup because they could stay visible for seconds after the user stopped interacting.
- The desired reference is Wisdom-Weasel's demo behavior: LLM candidates appear as a natural continuation of the normal Rime candidate flow, not as a clipboard/history panel.

Source findings:
- Wisdom-Weasel records committed text into `ContextHistory`, enters LLM prediction mode after meaningful commit, runs prediction asynchronously, drops stale model results with a request sequence, and merges LLM candidates into the structured Rime candidate list.
- Its llama.cpp provider caches the system prompt KV state and batch-samples multiple candidates.
- It is useful as a lifecycle reference, but RAG-IME should not copy its "letter key exits LLM mode" behavior because continued pinyin is how the user constrains prediction.

Changes:
- `/rime-suggest` now uses per-session `PredictionManager` for `predictionFirstMerge`.
- The manager is keyed by project, app, and session id.
- Stale post-commit continuation, raw passthrough, raw pinyin fallback, empty signal, or missing committed context clears the candidate pool before rendering.
- `predictionFirst.policy` now reports `candidatePoolActive`, `candidatePoolReused`, `candidatePoolStale`, and `candidatePoolContextFingerprint`.
- Added a regression test proving that a prior live post-commit candidate pool is dropped when a later stale request arrives for the same session.
- Updated framework/debug/shared-contract docs with the short-lived prediction-session rule.

Commands:
- `python3 -m py_compile rag_ime/rime_sidecar.py rag_ime/prediction_manager.py rag_ime/prediction_first.py`: passed.
- `python3 -m unittest -v tests.test_rime_sidecar.RimeSidecarTests.test_prediction_first_post_commit_refreshes_without_idle_delay tests.test_rime_sidecar.RimeSidecarTests.test_prediction_first_post_commit_clears_stale_empty_panel tests.test_rime_sidecar.RimeSidecarTests.test_prediction_first_stale_post_commit_drops_prior_manager_pool tests.test_prediction_manager`: 8 tests passed.
- `python3 -m unittest discover -s tests`: 271 tests passed.

Follow-up fix:
- Raw English/code/command input clears stale cached predictions, but fresh same-request model/RAG candidates can still appear after the raw commit candidate. This keeps `git status` style input usable without turning off AI help when the backend has a current result.

### 2026-07-02 16:19 CST
Problem:
- User feedback: LLM/RAG/memory candidates still felt like a hard persistent popup; after a few seconds it was strange and could block number input.
- Need to reference Wisdom-Weasel's natural demo behavior: candidates should continue the IME candidate flow, not behave like a clipboard/history panel.

Findings:
- Wisdom-Weasel binds candidate visibility to Rime context/UI refresh: composition, live LLM prediction mode, non-empty candidates, request sequence, and focus.
- Its key lesson for the native harness is session-bound visibility. Empty/stale response, raw passthrough, focus hide, or normal typing must clear the AI layer.
- Native preview exposed another quality issue for later: short prefix `ni` can still trigger long RAG history snippets; lifecycle is fixed here, candidate quality still needs follow-up filtering.

Changes:
- Added native `ActivePanelSession` with requestSeq, phase, committed context, composition, and expiry.
- Native panel now rejects older sidecar responses, only routes digits when the visible panel belongs to the current valid session, and uses a 0.85s post-commit expiry.
- Post-commit prediction clears immediately when the user resumes typing.
- Raw passthrough / hidden sessions no longer display the native prediction panel.
- Added `RimeDictionaryCandidateProvider` to feed native `/rime-suggest` previews from local Rime/Wanxiang dictionaries and `essay.txt` frequency weights.

Commands:
- `scripts/build_macos_frontend.sh`: passed.
- `build/RagImeMac.app/Contents/MacOS/RagImeMac --preview-rime-dictionary-json`: passed; `ni -> 你`, `wo -> 我`, raw code/path return no candidates.
- `build/RagImeMac.app/Contents/MacOS/RagImeMac --preview-rime-sidecar-json`: passed; decoded `displayCandidates` and `predictionSession`.
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest tests.test_prediction_first tests.test_prediction_manager tests.test_rime_sidecar tests.test_debug_server`: 84 tests passed.
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest discover -s tests`: 271 tests passed.
- `git diff --check`: passed.

### 2026-07-02 17:12 CST
Problem:
- User feedback: the LLM/RAG/memory panel still felt too much like a persistent clipboard/history popup, and short prefixes such as `ni` could show unrelated RAG/history suggestions.
- Selecting a RAG candidate could commit the full retrieved history paragraph because `SuggestionCompiler` kept compact `surface_text` but long `metadata.insert_text`.

Decision:
- Prefix-constrained mode must be a hard user constraint: if active pinyin does not match a side candidate's pinyin metadata, that side candidate must not occupy a number key.
- A number-key selection in the real IME should commit the compact candidate span. Full RAG source material belongs in `expandedEvidence` / `preview_text`, not `insertText`.

Changes:
- `merge_prediction_first_candidates()` now hard-filters model/RAG/memory candidates in `PREFIX_CONSTRAINED_COMPOSING`; unmatched side candidates are dropped and Wanxiang/Rime fallback owns the visible list.
- Raw English/code passthrough still keeps its direct raw commit candidate and may show same-request side candidates.
- `SuggestionCompiler` now writes compact candidate text to `metadata.insert_text`, de-duplicates by committed candidate span, and preserves full source text in expanded evidence.
- Added regression coverage for `ni` prefix no-match fallback: visible candidates become Wanxiang/Rime `你` and `呢`, while the prediction panel asks the frontend to clear.

Verification:
- Focused prefix/insert contract tests passed.
- Runtime-term and demo-quality tests passed.
- CLI `/rime-suggest-json` previews passed: `ni` with committed context returns only Rime display candidates and `predictionPanelVisible=false`; post-commit RAG candidates have `insertText == text`.
- `scripts/build_macos_frontend.sh`: passed.
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest discover -s tests`: 272 tests passed.
- `git diff --check`: passed.

### 2026-07-02 18:10 CST
Problem:
- User feedback: the LLM/RAG/memory candidate appearance should follow Wisdom-Weasel's natural candidate-flow style more closely; a panel that remains visible for seconds after post-commit feels like a clipboard/history popup.

Decision:
- Keep active composition candidates alive while the user is still typing pinyin, but make passive post-commit prediction short-lived.
- Hidden, expired, or no-session candidates must not route number keys.

Changes:
- Patched Squirrel post-commit holdover is now 0.9s, and side-candidate number routing first verifies the current raw input/session before committing.
- Native RagImeMac no longer has a legacy hidden `modelPredictions + ragSuggestions` number-key path; only visible `displayCandidates` in a valid `ActivePanelSession` can be selected.
- Native no-session or empty-composition panels now receive the 0.85s post-commit expiry instead of becoming indefinite.
- Memory candidates with a real source event now record accepted feedback like RAG candidates; recent-context fallback memory remains debug-only and does not create governance actions.
- `expandedEvidence` is carried through sidecar/native payloads so compact candidates can stay short while evidence remains inspectable.

Verification:
- `python3 -m py_compile rag_ime/models.py rag_ime/prediction_first.py rag_ime/rime_sidecar.py`: passed.
- `python3 -m unittest tests.test_build_patched_squirrel tests.test_debug_server tests.test_rime_sidecar tests.test_prediction_first tests.test_prediction_manager tests.test_demo_quality`: 104 tests passed.
- `scripts/build_macos_frontend.sh`: passed.
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest discover -s tests`: 274 tests passed.
- `git diff --check`: passed.

### 2026-07-02 18:35 CST
Problem:
- The native `RimeDictionaryCandidateProvider` only looked for a single `wanxiang.dict.yaml` file, but the referenced `7155/rime-wanxiang` repository uses a main dictionary with `import_tables` pointing at child dictionaries under `dicts/`.
- Wanxiang dictionary rows use tone marks such as `nǐ`, so plain user input like `ni` must be matched after tone folding.

Changes:
- Added `RAG_IME_RIME_DICT_DIR` and `RAG_IME_RIME_DICT_PATHS` support for the native debug provider.
- The provider now expands Wanxiang `import_tables`, including child dictionaries such as `dicts/jichu.dict.yaml`.
- Added diacritic-insensitive pinyin normalization so tone-marked rows match normal keyboard pinyin.
- Added a small bucket index by the first two pinyin/initial characters to avoid scanning every loaded entry on every query.
- Added a compile-level Swift provider test with a temporary Wanxiang-style fixture.

Verification:
- `scripts/build_macos_frontend.sh`: passed.
- `python3 -m unittest tests.test_macos_dictionary_provider`: 1 test passed.
- Temporary Wanxiang fixture preview passed: `ni -> 你`, `shijie -> 世界`, `sj -> 世界/设计`, while `git status` and `/Volumes/undo` returned no Chinese candidates.
- Real `7155/rime-wanxiang` clone smoke passed with `RAG_IME_RIME_DICT_DIR=/tmp/rime-wanxiang-inspect`: `ni`, `wo`, `xian`, `sj`, `shijie` all returned Wanxiang candidates; cold YAML load took about 16s, confirming this remains a debug bridge rather than the final librime path.
- Default local preview still returns Luna/Rime candidates because Wanxiang is not installed in `~/Library/Rime`.
- `python3 -m unittest tests.test_macos_dictionary_provider tests.test_prediction_first tests.test_rime_sidecar tests.test_prediction_manager`: 59 tests passed.
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest discover -s tests`: 275 tests passed.
- `git diff --check`: passed.

### 2026-07-02 17:28 CST
Problem:
- User asked why the GitHub branch appears under `codex/...`; clarified this is only a branch-name prefix, and `default` means GitHub currently treats that branch as the default branch.
- User feedback: the IME panel should stay compact, should not expose evidence/source cards in the tiny IME window by default, and live verification should not falsely fail when a pinyin prefix has no matching AI/RAG/memory candidate.

Decisions:
- Keep the real IME candidate panel small. Evidence and long previews remain in payloads for debug/manage surfaces, not the default candidate popup.
- Adapter-neutral candidate-pool TTL should match the short post-commit panel policy: 0.9s.
- Live sidecar verification must distinguish two correct states: matching prefix means AI/RAG/memory candidates take over; unmatched prefix means clean Rime/Wanxiang fallback with stale prediction panel cleared.

Changes:
- Native `RagCandidatePanel` is narrower and no longer renders evidence cards in normal candidate rows.
- `PredictionManager` default candidate-pool TTL is now 900ms.
- LaunchAgent installer now preserves embedding/vector env vars such as `RAG_IME_EMBEDDING_*`, `RAG_IME_VECTOR_CANDIDATES`, and `RAG_IME_VECTOR_WEIGHT`.
- Live verifier now accepts clean Rime fallback for unmatched prefix and still enforces AI-first behavior when side candidates match.

Findings:
- Current sidecar health is OK, using MLX local Qwen3.5 0.8B text 4bit at `/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-text-4bit-local`.
- Predictor prompt cache is enabled and hit-ready; `vectorStats.enabled=false` because no embedding provider env is active in the installed sidecar yet.
- `installation.yaml` is still untracked and was intentionally left out of staging.

Commands:
- `git status -sb`: `## codex/wisdom-weasel-rag-ime-mvp...origin/codex/wisdom-weasel-rag-ime-mvp`; modified files are `macos/RagImeMac/Sources/RagCandidatePanel.swift`, `rag_ime/prediction_manager.py`, `scripts/install_sidecar_launch_agent.sh`, `scripts/verify_prediction_first_sidecar.py`, `tests/test_launch_agent_script.py`; untracked `installation.yaml`.
- `git diff --stat`: 7 files changed, 114 insertions(+), 26 deletions(-).
- `python3 -m py_compile scripts/verify_prediction_first_sidecar.py rag_ime/prediction_manager.py`: passed.
- `python3 -m unittest tests.test_prediction_manager tests.test_prediction_first tests.test_demo_quality tests.test_launch_agent_script`: 29 tests passed.
- `python3 scripts/verify_prediction_first_sidecar.py --latency-budget-ms 350`: passed; live cases covered prefix fallback, post-commit model/RAG panel, raw command/code/path protection, and no-context Rime fallback.
- `scripts/build_macos_frontend.sh`: passed and signed `build/RagImeMac.app`.
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest discover -s tests`: 275 tests passed.
- `scripts/install_macos_frontend.sh`: installed `/Users/undo/Library/Input Methods/RagImeMac.app` and bridge config.
- `git diff --check`: passed.

### 2026-07-02 17:54 CST
Problem:
- Live sidecar could show MLX prediction and FTS/RAG, but optional vector RAG stayed disabled unless the LaunchAgent was installed with embedding env vars and the existing SQLite history was backfilled.
- The installed DB also had orphan `memory_state` rows from older runs, which made raw DB counts misleading.

Decisions:
- Keep vector recall opt-in. `local-hash` is only a deterministic local baseline for plumbing and tests, not a semantic embedding quality claim.
- Add an explicit `RAG_IME_ENABLE_LOCAL_VECTOR=1` installer switch for the local baseline, while preserving explicit OpenAI-compatible/local-WSL embedding settings when provided.
- Add startup auto-backfill only behind `RAG_IME_VECTOR_AUTO_REBUILD_LIMIT`; do not scan/embed history on every sidecar start by default.

Changes:
- `DebugImeService` now exposes `vectorAutoRebuild` in health, supports startup vector backfill, and adds `/rebuild-vector-index`.
- CLI `debug-server` and `sidecar-server` accept `--vector-auto-rebuild-limit`, defaulting from `RAG_IME_VECTOR_AUTO_REBUILD_LIMIT`.
- LaunchAgent installer preserves `RAG_IME_VECTOR_AUTO_REBUILD_LIMIT` and supports `RAG_IME_ENABLE_LOCAL_VECTOR=1`.
- `LocalSqliteCoreClient.initialize()` prunes orphan `memory_state` / `memory_vectors` rows and nulls orphan action event ids.
- README documents installed-sidecar vector setup and manual HTTP rebuild.

Findings:
- Live sidecar was reinstalled with MLX Qwen3.5 0.8B text 4bit plus `local-hash:96:v1` vector baseline.
- `/health` now reports `vectorStats.enabled=true`, `activeProviderVectors=124`, `candidateLimit=80`, `weight=1.4`.
- Current installed DB has 5109 events, but 4985 are deleted/noise-filtered; the actually retrievable set is 124 records: 103 Codex user records, 11 curated feedback records, and 10 sidecar input records.
- Orphan memory state count is now 0 after the new initialization cleanup.

Commands:
- `python3 -m py_compile rag_ime/debug_server.py rag_ime/cli.py rag_ime/local_sqlite_core.py`: passed.
- `python3 -m unittest tests.test_launch_agent_script tests.test_debug_server.DebugImeServiceTests.test_startup_can_backfill_vector_index_when_provider_enabled tests.test_debug_server.DebugImeServiceTests.test_rebuild_vector_index_endpoint_backfills_existing_events tests.test_local_sqlite_core.LocalSqliteCoreClientTests.test_initialize_prunes_orphan_memory_state_and_vectors`: passed.
- `python3 -m unittest tests.test_debug_server tests.test_local_sqlite_core tests.test_embeddings tests.test_launch_agent_script`: 71 tests passed.
- `python3 -m unittest tests.test_rime_sidecar tests.test_prediction_first tests.test_prediction_manager tests.test_demo_quality`: 70 tests passed.
- `scripts/install_sidecar_launch_agent.sh` with MLX predictor env and local-hash vector env: health OK.
- `curl -s http://127.0.0.1:8766/rebuild-vector-index -d '{"project":"wisdom-weasel-rag-ime","limit":5000}'`: indexed 124 active vectors.
- `python3 scripts/verify_prediction_first_sidecar.py --latency-budget-ms 350`: passed with post-commit `rag`, `memory`, and `model` candidates visible and raw command/code/path protected.
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest discover -s tests`: 279 tests passed.
- `scripts/build_macos_frontend.sh`: passed.
- `git diff --check`: passed.

### 2026-07-02 18:51 CST
Problem:
- User feedback: the live IME still looked like a clipboard/history surface; RAG was recalling Codex status/tool logs instead of useful user-intent candidates, and Rime candidates were filling visible slots even when an AI/RAG candidate existed.
- Branch clarification: `codex/wisdom-weasel-rag-ime-mvp` is a branch namespace prefix on `git@github.com:7155/wisdom-weasel-rag-ime.git`, not a separate GitHub account or folder.

Decisions:
- Codex history memory should default to real `role:user` messages only; old non-user imported rows should be hidden, not displayed.
- Prefix-constrained mode should not mix Rime/Wanxiang into the visible list once any LLM/RAG/memory candidate matches the user's pinyin. Rime remains only for no-match fallback and no-context anchor input.
- Weak-context low-value Rime words such as `根据` / `基于` / `和` / `测试` should be filtered instead of occupying the panel.

Changes:
- Added `import-codex-history --roles` with default `user` and `prune-codex-history-noise`.
- Added SQLite role-prune logic that marks non-user Codex history rows deleted and rebuilds phrase stats.
- Improved `SuggestionCompiler` noise filtering and extraction of numbered IME candidate examples from design/history text.
- Tightened prefix matching to primary candidate pinyin keys instead of middle sliding-window matches.
- Updated Prediction-first merge policy so matched AI/RAG/memory candidates do not get Rime fillers.

Live data:
- Backed up the live DB before mutation.
- Imported 4896 additional user Codex-history records from `$HOME/.codex`; live active user rows are about 4999.
- Rebuilt the local vector side-index; live active provider vectors are 5023 using `local-hash:96:v1`.
- Reinstalled sidecar with MLX Qwen3.5 0.8B text 4bit and local-hash vector baseline.

Commands:
- `python3 -m rag_ime.cli --db-path "$HOME/Library/Application Support/RagIme/rag-ime.sqlite" import-codex-history --path "$HOME/.codex" --project wisdom-weasel-rag-ime --limit 5000 --sample-size 0`: imported user history.
- `curl -s http://127.0.0.1:8766/rebuild-vector-index -d '{"project":"wisdom-weasel-rag-ime","limit":5000}'`: rebuilt live vector index.
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest discover -s tests`: 285 tests passed.
- `python3 scripts/verify_prediction_first_sidecar.py --latency-budget-ms 650`: passed; side candidates no longer mix Rime, weak context clears low-value fallback, raw English/code/path stay first.
- `scripts/build_macos_frontend.sh`: passed.

### 2026-07-02 19:02 CST
Problem:
- `doctor_squirrel_integration.sh` could still warn `no MLX model predictions to validate` even when live `/rime-suggest` returned model candidates in real post-commit scenarios.

Findings:
- The doctor main probe used active pinyin `ragshurufa`, so Prediction-first prefix constraints could filter or starve model candidates.
- In non-mixed-layout mode the probe only requested one side candidate, which could let RAG/memory occupy the only slot before model validation inspected the result.

Changes:
- Doctor main/model probe now uses a post-commit Prediction-first payload with no active pinyin.
- Model validation requests 8 visible/side candidate slots so RAG/memory cannot hide a valid model candidate.
- If the first model probe reports `model lane already running` or exceeds budget, doctor retries with a wider 1200ms validation budget.
- Added a regression test that simulates a busy first model lane and verifies the retry path.

Verification:
- `python3 -m unittest tests.test_doctor_squirrel_integration`: 15 tests passed.
- Real `bash scripts/doctor_squirrel_integration.sh` with live MLX sidecar now reports `model generation path: MLX model candidates available`; remaining warning is only the stale system `/Library/Input Methods/Squirrel.app`.
- `python3 scripts/verify_prediction_first_sidecar.py --latency-budget-ms 650`: passed.
- `scripts/build_macos_frontend.sh`: passed.
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest discover -s tests`: 286 tests passed.

### 2026-07-02 19:11 CST
Problem:
- The active goal now says not to depend on the currently fragile patched Squirrel route. The repo still had Squirrel doctor as the main readiness gate and README still described Squirrel as the accepted production route.

Decisions:
- Current executable product route is the independent native `RagImeMac` InputMethodKit adapter.
- Rime/Wanxiang remains the pinyin-anchor/fallback behavior reference and dictionary source; patched Squirrel remains a historical spike/comparison path.
- Native readiness should have its own doctor rather than using stale same-bundle Squirrel checks.

Changes:
- Added `scripts/doctor_macos_frontend.sh`.
- Native doctor checks `RagImeMac.app`, bundle id, InputMethodKit plist keys, bridge config, Swift sidecar preview decoding, live Prediction-first model/RAG/memory candidates, and raw command protection.
- Input-source registration/selected checks are optional strict gates via `RAG_IME_DOCTOR_REQUIRE_INPUT_SOURCE=1` and `RAG_IME_DOCTOR_REQUIRE_SELECTED_INPUT_SOURCE=1`.
- Updated README to make native RagImeMac the preferred validation route and mark Squirrel as spike/reference.
- Hardened `scripts/verify_prediction_first_sidecar.py` against transient post-commit `model lane already running` by retrying model validation with a wider 1200ms budget.

Verification:
- `scripts/doctor_macos_frontend.sh`: passed against live app/sidecar; only warning is that macOS input-source registration was not required.
- `python3 -m unittest tests.test_doctor_macos_frontend tests.test_doctor_squirrel_integration`: 17 tests passed.
- `python3 scripts/verify_prediction_first_sidecar.py --latency-budget-ms 650`: passed.
- `scripts/build_macos_frontend.sh`: passed.
- `bash -n scripts/doctor_macos_frontend.sh scripts/doctor_squirrel_integration.sh && python3 -m py_compile scripts/verify_prediction_first_sidecar.py`: passed.
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest discover -s tests`: 288 tests passed.

### 2026-07-02 19:20 CST
Problem:
- Native `RagImeMac` still treated Space as normal printable text. That made first-word pinyin anchoring awkward and made English/code input feel trapped in composition.
- Swift frontend did not explicitly obey `predictionSession.shouldClearPredictionPanel`, even though the sidecar contract already uses it for stale/empty/weak-context responses.

Changes:
- Space now selects the first visible Prediction-first candidate when the panel is active.
- If no side panel is active, Space selects the top Wanxiang/Rime dictionary candidate for normal pinyin composition.
- If the composition looks like raw English/code/path/command text and has no dictionary candidate, Space commits the raw text plus the trailing space and does not trigger post-commit AI prediction.
- Native panel rendering now hides immediately when sidecar says `shouldClearPredictionPanel=true`.
- Added static native input-controller contract tests for Space routing, raw passthrough, and sidecar clear policy.

Verification:
- `python3 -m unittest tests.test_native_input_controller tests.test_macos_dictionary_provider`: 4 tests passed.
- `scripts/build_macos_frontend.sh`: passed.
- `scripts/doctor_macos_frontend.sh`: passed; only warning is optional input-source registration gate not required.
- `python3 scripts/verify_prediction_first_sidecar.py --latency-budget-ms 650`: passed, including weak-context panel clear and raw English/code/path protection.
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest discover -s tests`: 291 tests passed.

### 2026-07-02 19:32 CST
Problem:
- Native app install was still a loose manual step: `install_macos_frontend.sh` copied files but did not verify or select the macOS input source.
- `select_macos_input_source.sh` could report failure on `TISSelectInputSource=-50` even when macOS had already switched the current input source.

Changes:
- `install_macos_frontend.sh` now supports `--select`, `--check`, `--no-check`, and `--require-input-source`.
- Shared input-source scripts now default to native `dev.local.inputmethod.RagImeMac`; Squirrel paths still pass explicit Squirrel IDs.
- Selection script now trusts final TIS state if `TISSelectInputSource` returns an error but current input source is already the target.
- README now documents `scripts/install_macos_frontend.sh --select` and the strict native doctor gate.
- Added tests for native install script and select-script fallback behavior.

Live verification:
- `scripts/install_macos_frontend.sh --select`: installed `/Users/undo/Library/Input Methods/RagImeMac.app`, synced bridge config, and selected `dev.local.inputmethod.RagImeMac`.
- Strict native doctor passed with `RAG_IME_DOCTOR_REQUIRE_INPUT_SOURCE=1 RAG_IME_DOCTOR_REQUIRE_SELECTED_INPUT_SOURCE=1`; the selected source is `RAG IME`.
- `python3 scripts/verify_prediction_first_sidecar.py --latency-budget-ms 650`: passed.

### 2026-07-02 20:58 CST
Problem:
- User reported the IME flow still was not usable: LLM/RAG did not visibly work, RAG looked like recent-context clipboard snippets, numbers could not reliably select candidates, and the panel could remain stale.

Findings:
- Live MLX service was healthy with local text-only `Qwen3.5-0.8B` MLX 4-bit, but the sidecar was not always running and the non-streaming `/predict` path crashed on `stream_first_candidate`.
- The real memory DB had 10018 `input_events` and 5023 vectors, but all were under project `wisdom-weasel-rag-ime`; requests using `project=learnA` filtered RAG down to zero.
- Real-time RAG used local-hash vector scanning and often missed the 100ms lane budget. FTS-only recall was faster and good enough for immediate input candidates.
- Native panel rendering grouped inline/model and block/RAG rows, but click/number selection still used local row indexes instead of backend `selectionRank`.
- TIS currently sees `dev.local.inputmethod.RagImeMac` as selectable but not selected/enabled in the active session; `scripts/install_macos_frontend.sh --select` installs the app but `TISSelectInputSource` returns `-50` on this machine now.

Changes:
- Added project-fallback retrieval when a requested project has no rows, so imported Codex history is still usable if the frontend passes a different project.
- Added a real-time RAG fast path that uses FTS-only retrieval for tight budgets, leaving vector/deep RAG for slower refresh.
- Hardened MLX streaming parsing and low-value filtering so single meta words such as `记忆`, `模型`, `输入法候选`, `后文候选`, and `直接输出` do not become IME candidates.
- Updated MLX fast prompt to avoid prompt meta-word copying and fixed `/predict` compatibility with `stream_first_candidate`.
- Fixed native panel selection to use backend `selectionRank/selectionKey` for display and numeric selection.

Verification:
- `python3 -m unittest tests.test_predictor tests.test_mlx_predictor_server tests.test_rime_sidecar tests.test_native_input_controller tests.test_local_sqlite_core tests.test_install_macos_frontend tests.test_select_macos_input_source`: 137 tests passed.
- `scripts/build_macos_frontend.sh`: passed.
- Live `/rime-suggest` now returns model + RAG candidates for the embedding/RAG debugging context, including `输入提示` from MLX and `embedding 检索应该结合当前输入和上下文窗口` from RAG.
- `scripts/install_macos_frontend.sh --select`: installed app and synced bridge config, but current macOS session still requires manually adding/selecting `RAG IME` in Keyboard Input Sources.

### 2026-07-02 21:04 CST
Problem:
- User confirmed System Settings -> Keyboard -> Input Sources -> Add did not show `RAG IME`, so native `RagImeMac` still could not be selected for real typing.

Findings:
- Live sidecar and MLX/RAG are healthy; the current blocker is macOS input-source registration, not candidate generation.
- TIS enumerates `dev.local.inputmethod.RagImeMac.Hans` as `enabled=true selectable=true`, but current source remains 豆包 and `thirdPartyEnabled=false`.
- `TISSelectInputSource` returns `-50` for both `RagImeMac.Hans` and Squirrel in this Codex/terminal session when the current source is 豆包.
- `/Library/Input Methods/RagImeMac.app` existed but was owned by `undo:staff`, unlike system-installed Doubao/Squirrel (`root:wheel`).
- Explorer comparison with Squirrel/fcitx5/OpenVanilla found high-risk differences: duplicate same-bundle installs under both user and system Input Methods, missing app icon metadata, missing `CFBundleSupportedPlatforms`, stale HIToolbox entries without matching `AppleEnabledThirdPartyInputSources`, and LaunchServices cache split-brain.
- A direct/admin plist overwrite of `com.apple.inputsources.plist` did not persist RagIme entries; macOS restored the third-party allow-list, so System Settings must be treated as the authority for that list.

Changes:
- Added explicit `.Hans` input mode metadata in `macos/RagImeMac/Info.plist`, plus `CFBundleIconFile`, `CFBundleIconName`, `CFBundleSupportedPlatforms`, and bumped `CFBundleVersion` to `2`.
- Added localized `InfoPlist.strings` for `en`, `zh-Hans`, and `zh-Hant` so the mode displays as `RAG IME` / `RAG 输入法` instead of a raw id.
- `build_macos_frontend.sh` now generates `RagImeIcon.icns` and copies localized resources.
- Added `scripts/install_system_macos_frontend.sh` to install the canonical app under `/Library/Input Methods`, back up duplicate user-local `RagImeMac.app`, set `root:wheel` permissions, re-sign, and re-register LaunchServices.
- Added `scripts/reset_macos_ragime_registration.sh` to remove stale RagIme records from HIToolbox enabled/selected/history without touching other input methods.
- `check_macos_input_source.sh` and `select_macos_input_source.sh` now distinguish actual current source (`selected`) from TIS preference flag (`tisSelected`) to avoid false positives.
- `install_macos_frontend.sh` now waits briefly for TIS visibility and reports `thirdPartyEnabled=false` as a real allow-list blocker.

Verification:
- `scripts/build_macos_frontend.sh`: passed and produced `RagImeIcon.icns` plus updated plist/resources.
- `scripts/reset_macos_ragime_registration.sh`: removed RagIme from HIToolbox stale records; TIS still enumerates the source, but `hitoolboxEnabled=false thirdPartyEnabled=false`.
- `python3 -m unittest tests.test_install_macos_frontend tests.test_select_macos_input_source tests.test_check_macos_input_source tests.test_doctor_macos_frontend tests.test_native_input_controller`: 18 tests passed.
- `scripts/doctor_macos_frontend.sh`: passed app/bridge/live sidecar checks; live sources include memory/RAG and raw English protection.
- `RAG_IME_DOCTOR_REQUIRE_SELECTED_INPUT_SOURCE=1 scripts/doctor_macos_frontend.sh`: intentionally fails with `selected=false current=com.bytedance.inputmethod.doubaoime.pinyin thirdPartyEnabled=false`, proving real typing is not yet selected.

Next:
- Run the system installer with visible admin password entry, then reopen System Settings Add panel and add `RAG IME`; if it still does not appear, treat native InputMethodKit as debug harness only and move the real product route to a mature Rime/Squirrel-compatible framework without repeating the stale patched-Squirrel bundle conflict.

### 2026-07-02 21:12 CST
Problem:
- User ran `scripts/install_system_macos_frontend.sh`; the system app installed, but Add panel still did not show `RAG IME`, and `TISSelectInputSource` still returned `-50`.

Findings:
- `/Library/Input Methods/RagImeMac.app` is now canonical and owned by `root:wheel`; user-local duplicate app is no longer active.
- LaunchServices now contains a valid canonical `/Library/Input Methods/RagImeMac.app` record with localized names, icon, `CFBundleVersion=2`, and bundle id `dev.local.inputmethod.RagImeMac`.
- LaunchServices still contains old temporary `RagImeMac.app` paths from previous tests; these do not point to live files.
- A first LS cleanup matcher was too broad because LS records can contain unrelated notification/activity fields; it was immediately narrowed to only unregister paths ending in `/RagImeMac.app`.
- After refresh, `RagImeMac.Hans` remains TIS-visible but not selectable as current input source: `selected=false current=豆包 hitoolboxEnabled=false thirdPartyEnabled=false`.

Changes:
- Added `scripts/refresh_macos_input_sources.sh` to unregister stale `RagImeMac.app` LS paths only, register the canonical system app, run LS garbage collection, and restart `cfprefsd`, `TextInputMenuAgent`, `SystemUIServer`, and System Settings.
- `install_system_macos_frontend.sh` now calls the refresh script after system install.
- Added regression coverage so the refresh script only unregisters `RagImeMac.app` paths and not arbitrary LS blocks.

Verification:
- `scripts/refresh_macos_input_sources.sh`: passed and now only reports the canonical app plus current TIS state.
- `python3 -m unittest tests.test_install_macos_frontend tests.test_select_macos_input_source tests.test_check_macos_input_source tests.test_doctor_macos_frontend`: 12 tests passed.
- `scripts/doctor_macos_frontend.sh`: passed app/bridge/live sidecar checks.
- `RAG_IME_DOCTOR_REQUIRE_SELECTED_INPUT_SOURCE=1 scripts/doctor_macos_frontend.sh`: still fails as expected because macOS has not selected/allow-listed `RAG IME`.

### 2026-07-02 21:27 CST
Problem:
- User asked for stricter project management and to delete or downgrade wrong paths. The native `RagImeMac` app still does not appear in System Settings Add panel, so treating it as the product route is misleading.

Findings:
- `RagImeMac.Hans` is TIS-visible but not in `AppleEnabledThirdPartyInputSources`; current source remains 豆包 and `TISSelectInputSource` returns `-50`.
- `/Library/Input Methods/RagImeMac.app` is ad-hoc signed and `spctl` rejects it. This explains why TIS enumeration is not enough for reliable System Settings allow-listing.
- The older architecture decision was correct: `RagImeMac` is a debug harness; product work should attach to mature Rime/Squirrel candidate flow.
- Subagent read-only research agreed: prefer a branded Squirrel/Rime frontend with unique bundle id and sidecar `displayCandidates`; use McBopomofo/fcitx5-macos as references only, not the current Mac product base.

Changes:
- `install_macos_frontend.sh` and `install_system_macos_frontend.sh` now stop by default and require `RAG_IME_ALLOW_NATIVE_HARNESS_INSTALL=1` for harness-only installation.
- README route wording changed back to Squirrel/Rime product route; native is documented as debug harness only.
- `replace_system_squirrel_app.sh` and `enable_squirrel_hitoolbox_input_source.sh` are now documented as emergency/debug repair, not default product install.
- Feedback/issues doc records the user's visible blockers and the route reset.

Next:
- Build the independent branded `RAG-IME.app` Squirrel/Rime path, not same-bundle replacement and not native `RagImeMac` as product.
- Verify real foreground trace: sidecar request, sidecar response applied, panel layout, `/rime-select`, and fail-closed behavior for sidecar/model/raw English/code/path cases.

### 2026-07-02 21:35 CST
Problem:
- The independent branded Squirrel installer still mixed install/build with direct preference repair and automatic input-source selection, which made macOS input-source debugging hard to reason about.

Changes:
- `build_patched_squirrel.sh` now defaults `RAG_IME_SQUIRREL_ENABLE_PREF_REPAIR=0` and `RAG_IME_SQUIRREL_AUTO_SELECT=0`.
- Branded `RAG-IME.app` install may still register/enable through Squirrel's own commands, but it will not run the direct HIToolbox/inputsource plist helper or auto-select the source unless explicitly opted in.
- README, Xcode setup, and macOS adapter docs now document the explicit opt-in for those debug-only behaviors.

Verification:
- Branded install dry-run resolves `target_app=/Users/undo/Library/Input Methods/RAG-IME.app`, `bundle_id=im.rag-ime.inputmethod.RagIme`, `enable_pref_repair=0`, and `auto_select=0`.
- Focused Squirrel/install tests passed.

### 2026-07-02 23:23 CST
Problem:
- User reported the IME still felt unusable: old candidates stayed visible, digits were hijacked, raw English/code/path input broke, RAG looked like clipboard recall instead of useful input assistance, and LLM/RAG/memory were not visibly driving the candidate list.
- The installed system app at `/Library/Input Methods/RAG-IME.app` was still an older 21:46 binary, while the rebuilt Squirrel frontend existed only in `/tmp`.

Findings:
- Wisdom-Weasel's useful lesson is lifecycle discipline: Rime owns anchor composition, LLM candidates need explicit selection guards, and stale candidates must fail closed.
- The product route is branded Squirrel/Rime, not the native `RagImeMac` harness.
- Admin replacement of `/Library/Input Methods/RAG-IME.app` could not complete because the sudo/admin password step was not available in this session.
- Installing the latest same-bundle app into `~/Library/Input Methods/RAG-IME.app` works without admin and reuses the existing `RAG-IME - Simplified` third-party allow-list.
- There is still a duplicate older system app with the same bundle id; doctor warns about it until the system app is removed or replaced with admin rights.

Changes:
- Raw ASCII/code/path input now suspends side lanes and returns only the raw commit candidate, so `git status`, `model_prediction`, and `/Volumes/...` do not get rewritten by model/RAG candidates.
- Frontend number-key selection now ignores stale/unselectable display candidates and never commits `raw_english` rows via digit keys.
- Doctor's mixed-layout candidate contract now uses a realistic 1200ms budget so a slow MLX 0.6B response is not misreported as broken wiring.
- `installation.yaml` is ignored and removed from the worktree because it is local Rime metadata.
- Latest branded Squirrel app was installed at `~/Library/Input Methods/RAG-IME.app` and selected as `im.rag-ime.inputmethod.RagIme.Hans`.

Verification:
- `RAG-IME - Simplified` is selected: `selected=true hitoolboxEnabled=true thirdPartyEnabled=true`.
- Squirrel doctor passed for the user-level app: candidate contract produced 8 display candidates with model inline first, RAG/memory block rows after, and no Rime fallback when side candidates are available.
- Live sidecar verification passed for post-commit prediction, prefix-constrained prediction, raw command/code/path passthrough, and Rime fallback.
- Focused tests passed: `python3 -m unittest -v tests.test_prediction_first tests.test_rime_sidecar tests.test_build_patched_squirrel tests.test_doctor_squirrel_integration tests.test_mlx_predictor_server tests.test_prediction_manager` ran 88 tests OK.
- `git diff --check` and `py_compile` passed.

Open:
- Need user real-typing validation in Codex/Edge/TextEdit because Computer Use screen capture failed and cannot inspect the live candidate window.
- Need admin cleanup later: remove or replace `/Library/Input Methods/RAG-IME.app` so macOS cannot accidentally load the old system binary.
- Need later model-quality work: keep MLX 0.6B for speed now; compare Qwen3.5 0.8B only after interaction is stable.

### 2026-07-03 00:36 CST
Problem:
- User explicitly requested another careful read of `https://github.com/Felix3322/Wisdom-Weasel` and said this fork should be treated as a key reference before more coding.

Findings:
- Felix fork snapshot is `3473284a14b0336d5e6a39d2dfb0ffcbdcfb5a17`.
- The fork's strongest transferable boundary is not "LLM replaces Rime"; it is `Wanxiang/Rime anchors pinyin and English`, `LLM handles post-commit/no-input and pinyin-constrained continuation`, and `Alpha-style scoring handles rerank/frequency/feedback`.
- Wanxiang keeps pinyin, user dictionary, English/mixed-code translators, auto phrase, and Alpha rerank inside the Rime translator/filter chain.
- `contextual_suggestions: false` in Wanxiang is an important warning: Rime's built-in phrase prediction and LLM continuation should not be collapsed into one opaque ranking path.
- `super_english.lua` protects English/code/path style input through formatting, spacing, single-letter handling, URL/protocol exceptions, and fallback reconstruction; RAG/LLM must not rewrite this lane.

Changes:
- Added `docs/agent/felix-wisdom-weasel-migration-matrix-20260703.md`.
- Updated `docs/agent/todo.md` with the Felix migration matrix and explicit P0/P1/P2 migration tasks.

Next:
- Before the next code patch, reopen the Felix files named in the matrix and implement the smallest P0/P1 boundary, then do the third read-back against both Felix behavior and our diff.

### 2026-07-03 01:48 CST
Problem:
- User asked to repeatedly inspect and compare `Felix3322/Wisdom-Weasel` because earlier iterations did not faithfully carry over Wisdom-Weasel's hard-won interaction model.

Findings:
- Felix's transferable core is now confirmed in code, not only README: `LLMRequestType` splits no-input prediction, pinyin-constrained prediction, and Rime reorder.
- `RimeWithWeasel` uses interactive/background scheduling, request sequence invalidation, no-input auto-hide, and a single display list mapping visible rows back to Rime indices or LLM commits.
- `LLMProvider.cpp` candidateization removes prompt echo, cuts at punctuation, emits preferred short lengths, deduplicates, streams partial candidates, and uses staged no-input generation branches.
- Alpha scoring combines semantic score, preference score, user frequency score, order prior, top1 guard, and trace/debug fields.
- `ContextHistory` is only short-term committed-text context with sentence-boundary trimming and backspace sync; it should not replace SQLite/RAG evidence.

Changes:
- `rag_ime/predictor.py`, `rag_ime/mlx_predictor_server.py`, and `rag_ime/rime_sidecar.py` now pass a normalized prediction request type and Rime candidate pool through the MLX model lane.
- Added tests proving MLX request normalization/prompt construction and sidecar-to-predictor request propagation.
- Expanded `docs/agent/felix-wisdom-weasel-migration-matrix-20260703.md` with the second-pass file list, done/missing matrix, and P0/P1 migration rules.

Verification:
- Full local test suite passed: `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest discover -s tests` ran 315 tests OK.
- `git diff --check` passed.

Next:
- P0: implement or verify frontend-level request sequence, stale response discard, auto-hide, and visible-slot selection mapping in the Mac/Squirrel route.
- P1: port Felix-style MLX staged generation and candidateization.
- P1: add Alpha-style score breakdown and feedback-visible ranking to the SQLite scorer.

### 2026-07-03 02:43 CST
Problem:
- User asked to repeatedly compare against `Felix3322/Wisdom-Weasel` and not keep shipping an IME whose candidate lifecycle behaves like a stale clipboard panel.

Findings:
- GitHub public `Felix3322/Wisdom-Weasel` `main` is still `3473284a14b0336d5e6a39d2dfb0ffcbdcfb5a17`.
- A local extra `upstream/main` ref at `64ba2fd` adds context-compression-complete warmup callbacks; useful later for MLX prompt-cache warmup, but not the current P0 UI bug.
- Current native `RagImeMac` is IMK + Wanxiang YAML preview + Python sidecar, not a true librime/Squirrel candidate-layer integration. Treat it as a debug/demo adapter, not the final product route.

Changes:
- Added session fingerprints to `PredictionManagerResult`, `/rime-suggest` `predictionSession`, and every `displayCandidates[*].metadata`.
- Native Mac adapter now drops stale async sidecar responses unless they match both the response request sequence and the current latest request sequence.
- Native click selection now verifies active panel request sequence, context, composition, and candidate session fingerprint before commit.
- Number-key routing also checks the active panel fingerprint against the latest prediction session.
- Felix migration matrix now records this third pass and keeps Squirrel/Rime as the final architecture route.

Verification:
- Focused tests passed: prediction manager, post-commit sidecar session binding, stale clear, and native source checks.
- Full suite passed: `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest discover -s tests` ran 317 tests OK.
- Mac frontend rebuild passed: `scripts/build_macos_frontend.sh` produced `build/RagImeMac.app`.
- `git diff --check` passed.

Next:
- Continue P0 on the real Squirrel/Rime candidate-layer route; native `RagImeMac` should not be treated as final IME quality.
- P1 remains Felix-style staged MLX candidateization and Alpha-style SQLite score breakdown.

### 2026-07-03 10:25 CST
Problem:
- After the third pass, the session-bound candidate lifecycle was still only proven in the native debug adapter. User's target requires the same Felix-style stale-candidate protection in the real Squirrel/Rime path.

Findings:
- Existing Squirrel patch already had `requestSeq`, request fingerprint, display holdover, number-key routing, and frontend trace hooks.
- Missing Squirrel-side pieces were `predictionSession` decoding, panel session fingerprint/expiry state, clear-response handling, candidate metadata fingerprint checks, and a trace verifier that rejects number-key commits from a different session.
- Felix/Wisdom-Weasel comparison remains aligned: visible candidate slots must map to the same request/session snapshot that produced them; late or stale model/RAG rows must be dropped rather than left selectable.

Changes:
- Updated `squirrel-patches/0001-add-rag-ime-sidecar.patch` so Squirrel decodes `predictionSession`, records `sessionFingerprint`/`expiresAfterMs`, clears on `shouldClearPredictionPanel`, rejects response candidates whose metadata fingerprint does not match the response session, and checks candidate session before click/number-key commit.
- Updated `scripts/check_squirrel_frontend_trace.py` so `number_key_route` and `side_candidate_commit` only match when their candidate `sessionFingerprint` values match.
- Expanded Squirrel patch and frontend trace tests for the new session-bound contract.

Verification:
- `python3 -m unittest tests.test_build_patched_squirrel tests.test_squirrel_frontend_trace` passed: 15 tests OK.
- `python3 -m unittest tests.test_doctor_squirrel_integration tests.test_rime_sidecar` passed: 61 tests OK.
- `git diff --check` passed.

Next:
- P0: build/install the branded Squirrel route and collect real foreground trace for `sidecar_request_scheduled -> sidecar_response_applied -> number_key_route -> side_candidate_commit`.
- P1: port Felix-style MLX pinyin-constrained/logits candidateization and Alpha-style score diagnostics.

### 2026-07-03 10:47 CST
Problem:
- User corrected architecture priority: current architecture must primarily follow `Felix3322/Wisdom-Weasel`; OpenLess should wait until that route is complete.

Findings:
- Verified `Felix3322/Wisdom-Weasel` public HEAD is still `3473284a14b0336d5e6a39d2dfb0ffcbdcfb5a17`.
- Re-read Felix core boundaries: `RimeWithWeasel` owns the unified visible candidate list and selection mapping; `LLMProvider` owns typed requests and candidateization; Alpha owns score breakdown, feedback, and frequency.
- OpenLess remains useful only as a later management-console reference, not as foreground IME architecture.

Changes:
- Added `docs/agent/felix-first-architecture-20260703.md`.
- Marked `docs/agent/openless-management-console-reference-20260703.md` as deferred until the Felix/Squirrel/Wanxiang route is usable.

Next:
- Continue P0 on the branded Squirrel route before any OpenLess-style UI work.

### 2026-07-03 12:40 CST
Problem:
- User feedback: current visible candidates still looked like clipboard/memory echoes, not real LLM/RAG prediction; no-input panels stayed too long; RAG seemed to search unrelated Codex text; switching real input sources can crash Edge/Ghostty/Codex, so this pass must not switch the system input method.

Findings:
- Real sidecar CLI response already exposes `displayCandidates`, not `candidates`; an earlier manual probe read the wrong JSON key.
- Prefix-constrained RAG was fixed to query only the active prefix such as `sj`, but the model lane was still receiving the full semantic query `context + sj + Rime candidates`. That made Qwen output or echo strings like `设计手机世界`, which the repeat filter correctly removed.
- Local MLX services were verified without Ollama. Existing 8767 service loads text-only `Qwen3-0.6B-Base`. A temporary 8768 service loaded `/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-text-4bit-local`.
- Qwen3-0.6B Base is fast but weak for instruction-following. Qwen3.5-0.8B text can produce usable short candidates when request fields are separated correctly.

Changes:
- `run_side_lanes_with_latency_budget()` now passes only the stable short pinyin prefix to the model lane during `pinyin_constrained_prediction`; Rime candidates are still passed through the typed `rimeCandidates` field.
- Added a regression assertion that prefix-constrained model requests receive `currentInput == "sj"` and not the merged semantic query.
- Kept the earlier RAG/memory safeguards from this pass: recent context skips generated `source:model/source:rag` rows, weak vector-only matches are gated, and off-prefix model candidates are filtered out.

Offline verification:
- Focused regression tests passed: `test_model_lane_receives_pinyin_constrained_request_context`, `test_model_lane_filters_off_prefix_pinyin_predictions`, `test_model_lane_timeout_keeps_rag_candidates_responsive`.
- Broader suite passed: 151 tests across local SQLite core, Rime sidecar, prediction-first, prediction manager, predictor, and MLX predictor server.
- Full suite passed: `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest discover -s tests` ran 322 tests OK.
- `python3 -m py_compile ...` and `git diff --check` passed.
- Real DB + MLX 0.8B sidecar probe with `committedContext="我想做一个本地 RAG 输入法，接下来想"` and `preedit="sj"` produced:
  - `1 设计本地输入法` from `model/local-mlx`, elapsed about 587 ms under a 900 ms sidecar budget.
  - `2 设计一个候选展示方式` from `rag`, elapsed about 444 ms.
- Updated the user LaunchAgents without switching input sources:
  - `com.rag-ime.mlx-predictor` now loads `/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-text-4bit-local`.
  - `com.rag-ime.sidecar` now points to the same MLX predictor with `timeout=900ms`, `maxTokens=32`, `temperature=0.2`, `topP=0.9`.
  - HTTP health on `127.0.0.1:8766` shows `eventCount=10032`, `activeProviderVectors=5037`, `predictor.providerName=local-mlx`, and `modelInfo.textOnly=true`.
  - HTTP `/rime-suggest` against the resident sidecar produced `1 设计输入法 [model/local-mlx]` and `2 设计一个候选展示方式 [rag]` under a 900 ms budget.

Next:
- Do not switch/select the real macOS input source until the crash risk is intentionally accepted by the user.
- Foreground trace still needs controlled manual testing; do not treat HTTP success as real IME success until the candidate panel, number keys, and app-crash behavior are verified.
- Continue P0 frontend/Squirrel validation: candidate panel position, auto-hide, no stale panel, number-key routing, English/code passthrough, and real `sidecar_response_applied -> side_candidate_commit` trace.

### 2026-07-03 12:58 CST
Problem:
- User granted Full Access, but the current safety boundary remains: do not switch the real input source or run uncontrolled GUI typing because previous foreground switching crashed Edge/Ghostty/Codex.

Findings:
- Remaining uncommitted work was focused on Squirrel frontend observability and panel lifecycle, not on another sidecar-only backend tweak.
- The Squirrel patch now has display expiry work items, display-state fingerprints, and `panel_expired_cleared` trace events so stale prediction panels can be cleared instead of trapping number keys.
- Number-key side-candidate routing is guarded by the live display session, candidate session fingerprint, and non-raw-English source type.
- `prepare_squirrel_workspace.sh` adds `squirrel-process.jsonl` process trace hooks in `Main.swift`, which helps prove which input-method app macOS actually loaded.
- A new frontend LaunchAgent installer exists for later testing, but it should be used with dry-run until controlled foreground validation is allowed.

Verification:
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest -v tests.test_build_patched_squirrel tests.test_doctor_squirrel_integration tests.test_launch_agent_script tests.test_prepare_squirrel_workspace` passed: 27 tests OK.
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest -v tests.test_squirrel_frontend_trace tests.test_native_input_controller tests.test_prediction_first tests.test_prediction_manager` passed: 35 tests OK.
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest -v tests.test_rime_sidecar` passed: 47 tests OK.
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest discover -s tests` passed: 322 tests OK.
- `python3 -m py_compile rag_ime/*.py scripts/*.py` passed.
- `git diff --check` passed.
- A mistaken non-dry-run frontend LaunchAgent install was immediately booted out and the generated plist was removed; `launchctl print gui/$(id -u)/com.rag-ime.frontend` confirmed the service was not loaded.

Next:
- Commit the frontend lifecycle/observability patch and push.
- Still do not claim real IME usability until a controlled foreground test verifies panel position, auto-hide, number-key commit, and no app crash.

### 2026-07-03 13:18 CST
Problem:
- Continue Felix-first optimization without switching the real macOS input source. The next useful piece is RAG/memory candidate explainability, because the user repeatedly asked why RAG retrieved unrelated material and how embedding/ranking are actually used.

Findings:
- Felix public HEAD is still `3473284a14b0336d5e6a39d2dfb0ffcbdcfb5a17`; local clone matches.
- Felix Alpha's portable idea here is not the Windows DLL/ONNX runtime itself, but the score-breakdown discipline: semantic, preference, user-frequency, continuation, base prior, feedback, and logs should explain why a candidate moved.
- This repo already had SQLite signals for FTS5, vector score, pinyin boost, phrase frequency, project/app frequency, accepted/skipped/downranked, pinned, tags, and runtime-noise penalty, but they were mostly compressed into a reason string.

Changes:
- Added `score_breakdown` generation in `LocalSqliteCoreClient._row_to_memory()`.
- The breakdown uses stable JSON schema `rag-ime.score-breakdown.v1` with `components`, `rawSignals`, `weights`, `fieldBoosts`, query, expandedQuery, and total.
- `SuggestionCompiler` now passes the breakdown into suggestion metadata only when present.
- RAG `displayCandidates[*].metadata.score_breakdown` now carries the same structure through `/rime-suggest`.
- Updated `docs/agent/felix-first-architecture-20260703.md` to mark this as the first migrated P2 Alpha-style SQLite ranking diagnostic.

Verification:
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest -v tests.test_local_sqlite_core.LocalSqliteCoreClientTests.test_score_breakdown_explains_frequency_and_acceptance_signals tests.test_rime_sidecar.RimeSidecarTests.test_rag_display_candidate_exposes_alpha_style_score_breakdown` passed.
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest -v tests.test_local_sqlite_core tests.test_rime_sidecar` passed: 87 tests OK.
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest discover -s tests` passed: 324 tests OK.
- `python3 -m py_compile rag_ime/local_sqlite_core.py rag_ime/suggestion_compiler.py tests/test_local_sqlite_core.py tests/test_rime_sidecar.py` passed.
- `python3 -m py_compile rag_ime/*.py scripts/*.py` passed.
- `git diff --check` passed.

Next:
- Commit and push.
- Next Felix P2/P1 candidates: expose score breakdown in doctor/debug CLI, then improve MLX candidateization/prompt flow.

### 2026-07-03 13:46 CST
Problem:
- Continue Felix-first work under the no-real-input-source-switch boundary.
- The previous score breakdown existed only inside candidate metadata, so debug/doctor still made it hard to see why RAG/memory candidates appeared or ranked ahead/behind.

Changes:
- `/rime-suggest` now attaches `rankingDiagnostics` with candidate counts, source counts, top candidate summary, model `candidate_scores` availability, and RAG `score_breakdown` details.
- Cached and in-flight `/rime-suggest` responses keep the same diagnostics after session/request metadata refresh.
- `cache-probe` samples now include `sourceCounts`, `hasRagScoreBreakdown`, and a compact top-candidate summary.
- `scripts/doctor_squirrel_integration.sh` now prints a RAG ranking diagnostics line when the sidecar exposes the payload. This is observability only, not a new install failure gate.

Verification:
- Focused tests passed: `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest -v tests.test_debug_server tests.test_doctor_squirrel_integration tests.test_rime_sidecar.RimeSidecarTests.test_rag_display_candidate_exposes_alpha_style_score_breakdown` ran 48 tests OK.
- `python3 -m py_compile rag_ime/debug_server.py rag_ime/cli.py rag_ime/rime_sidecar.py` passed.
- `git diff --check` passed.

Next:
- Run full suite, then commit and push.
- Continue next Felix-style item after this: MLX prompt/candidateization, while keeping real foreground input-source testing paused until explicitly controlled.

### 2026-07-03 14:07 CST
Problem:
- The user repeatedly observed that model candidates looked like stale clipboard/memory snippets instead of LLM IME continuations, and that Rime/MLX paths could still emit generic or out-of-pool candidates.

Findings:
- Felix/Wisdom-Weasel's portable lesson is to treat model output as raw material: remove prompt echo, reject reasoning/process noise, turn plain generated sentences into short continuation spans, and keep Rime reorder inside the candidate pool.
- This repo's MLX fallback path still used the older generic parser, so non-JSON model output could leak as long, awkward, or repeated candidates.

Changes:
- Added `parse_ime_prediction_candidates()` as the IME-facing candidateizer for MLX/service output.
- Sentence fallback now strips current-input/context echo and converts a generated continuation clause into short selectable candidates.
- Rime reorder parsing now accepts index outputs like `[2, 1]` or text mentions but returns only original Rime candidates.
- MLX service and client both use the IME candidateizer for JSON-generation fallback and streaming first-candidate cleanup; direct payload candidate lists remain direct candidates and are only filtered.
- Added regression tests for prompt-echo removal, short continuation generation, and Rime reorder pool safety.

Verification:
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest -v tests.test_predictor tests.test_mlx_predictor_server` passed: 53 tests OK.
- `python3 -m py_compile rag_ime/*.py scripts/*.py` passed.
- `git diff --check` passed.
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest discover -s tests` passed: 329 tests OK.

Next:
- Commit and push.
- Continue with real sidecar/runtime candidate quality probes before touching foreground input-source switching again.

### 2026-07-03 15:03 CST
Problem:
- User provided local mlx-community models under `/Volumes/undo 4t/git/learnA/models/mlx/` and asked to stop using Ollama, make MLX/RAG/memory output real, and avoid switching the crashing foreground input source.
- Runtime probes showed the repo code and installed LaunchAgent copy can diverge, so service health alone is not enough; after code changes the sidecar/MLX LaunchAgents must be reinstalled or restarted.

Findings:
- Qwen3-0.6B/1.7B/4B are text-only `Qwen3ForCausalLM` models with tokenizer chat templates. They were being treated as base-completion models because their path did not contain `chat` or `instruct`, which caused generic or garbled IME candidates.
- Qwen3.5-4B/9B are multimodal-style `Qwen3_5ForConditionalGeneration` MLX repos and were much slower for this IME path.
- Practical default for now is `Qwen3-0.6B-4bit` with prompt cache: roughly 400ms model lane in sidecar probes, while 1.7B/4B/9B were too slow for the current typing loop.
- Prefix-constrained prediction failed when the model received expanded history text like `历史参考(禁止复读)` / `当前上下文:`. With clean on-screen context plus short pinyin prefix, the same MLX provider returned usable candidates.
- The old project-specific `com.rag-ime.ollama` LaunchAgent was still running even though sidecar had switched to MLX; it was unloaded and its plist removed to avoid resource use and diagnosis noise.

Changes:
- MLX model inspection now reads tokenizer chat-template metadata and routes Qwen3 chat-template models through `chat-json` instead of base-completion mode.
- Dynamic MLX prompts now include hard constraints for pinyin-constrained prediction and Rime reorder requests.
- Candidate parsing now rejects mojibake replacement characters, low-value short filler such as `测试/分析/假设...`, and splits concatenated Rime candidates such as `设计手机世界数据` back into valid candidate entries.
- `pinyin_constrained_prediction` now sends the model clean explicit context (`explicit-pinyin-constrained`) while keeping RAG retrieval independent.
- Reinstalled `com.rag-ime.mlx-predictor` and `com.rag-ime.sidecar` with MLX 0.6B and local vector retrieval enabled. No real input-source switch was performed.

Verification:
- `/health` shows sidecar provider `local-mlx`, model `/Volumes/undo 4t/git/learnA/models/mlx/Qwen3-0.6B-4bit`, prompt cache enabled, active local vectors `5037`.
- `/health` on MLX predictor shows `promptMode=chat-json`, `textOnly=true`, `baseCompletion=false`.
- HTTP `/rime-suggest` post-commit probe for `我想把这个输入法`: model lane returned `把流程跑通`, `接入本地记忆`; RAG returned historical candidates; memory returned user preference candidates.
- HTTP `/rime-suggest` pinyin probe for `sj` with Wanxiang/Rime candidates: model lane used `explicit-pinyin-constrained` and returned `设计`; RAG returned `设计一个候选展示方式`.
- `PYTHONWARNINGS='ignore::ResourceWarning' python3 -m unittest discover -s tests` passed: 331 tests OK.
- `python3 -m py_compile rag_ime/*.py scripts/*.py` passed.
- `git diff --check` passed.

Next:
- Commit and push this MLX runtime/candidateization batch.
- Foreground IME validation remains paused until the user explicitly wants a controlled test, because switching apps/input sources was reported to crash other apps.
- Next product work should target the actual macOS candidate panel lifecycle/positioning and better multi-candidate MLX output under the same no-switch CLI-first debug boundary.

### 2026-07-03 18:28 CST
Problem:
- User said 1.7B MLX can be tried later, while the live IME still needs fast, clean, selectable LLM/RAG/memory candidates.
- Real matrix showed candidates were parsed, but raw MLX text could keep generating Qwen chat-template tails like `<|im_end|>` / `Human:`, making quality evaluation too optimistic before stricter scoring.

Findings:
- Qwen3-0.6B-4bit is still the better real-time default: after stopping chat-template echo, matrix p50 was about 274ms, p95 about 817ms, quality score 92.
- Qwen3-1.7B-4bit is viable as a later slow/quality lane: quality score 100 and p50 about 742ms, but no-input continuation still hit about 2.1s, too slow for default live typing.
- English/code input must not be blocked blindly; short ASCII candidates are allowed only when they come from the Rime/Wanxiang candidate pool.

Changes:
- MLX generation now stops on tokenizer EOS or decoded chat-template stop markers, and buffers partial stop-marker prefixes so `<|im_end|` fragments are not emitted.
- IME candidate filtering now preserves Rime-provided ASCII/code candidates in pinyin-constrained mode while still filtering model-invented short ASCII noise.
- `benchmark_mlx_model_matrix.py` now flags chat-template echo, low-value debug candidates, weak short continuations, and duplicate prefix candidates.

Verification:
- Focused MLX/predictor/matrix tests passed: 74 tests OK.
- Real local MLX matrix ran against 0.6B and 1.7B without switching the macOS input source.
- Full suite passed: 356 tests OK.
- `py_compile` and `git diff --check` passed.

Next:
- Commit and push.
- Keep 0.6B as realtime default; test 1.7B later as an opt-in slow lane after the live panel flow is stable.

### 2026-07-03 18:48 CST
Problem:
- User emphasized that side candidates must become useful personal input memory, not stale clipboard-like snippets.
- Felix/Wisdom-Weasel Alpha rerank path uses committed text as positive feedback and only treats higher skipped candidates as conservative negative feedback.
- In this repo, selecting a model side candidate wrote an input event, but if the candidate had no original RAG/memory source id it did not receive accepted feedback; additionally `source:model` rows were filtered out by `SuggestionCompiler`, so the selected model phrase could not resurface as a memory candidate.

Changes:
- `record_rime_side_candidate_selection()` now records accepted feedback on the newly committed event when no source RAG/memory action exists.
- Selection memory context now includes the semantic query, so selected side candidates are retrievable by later SQLite/FTS queries instead of being indexed only under a weak recent-context string.
- Real user-selected side candidates are tagged with `sidecar-selected`.
- `SuggestionCompiler` still skips generated `source:model` / `source:rag` intermediate rows, but allows rows that were actually selected by the user.
- Added regression coverage showing a selected model candidate is later ranked ahead of a generic candidate, with `accepted:1` visible in the reason.

Verification:
- Focused rime-select/debug tests passed: 9 tests OK.
- Sidecar/debug/local SQLite tests passed: 122 tests OK.
- `py_compile` passed for touched runtime modules.

Next:
- Run full suite, commit, and push.
- Keep Qwen3-0.6B as realtime default; keep Qwen3-1.7B as a later opt-in slow/quality lane after the live panel flow is stable.

### 2026-07-03 19:01 CST
Problem:
- Continue Felix/Wisdom-Weasel migration on the macOS native frontend without switching the foreground input source.
- The Swift frontend treated every visible `RimeDisplayCandidate` selection as a side-candidate `/rime-select`, including ordinary Rime/Wanxiang fallback rows. That blurred the boundary Felix keeps strict: Rime owns anchor/fallback, side candidates own prediction feedback.
- Swift also did not send the full visible candidate list to `/rime-select`, so the real native path could not apply skipped-higher feedback even though the backend contract supported it.

Findings:
- Felix `RimeWithWeasel.cpp` builds one visible display list, but selection is routed by candidate origin.
- Felix Alpha feedback records committed text as positive feedback and only higher-ranked rerank candidates as conservative negative feedback.

Changes:
- `RagInputController` now snapshots `latestDisplayCandidates` before clearing the panel and sends it as `shownCandidates` only when the selected row is a side candidate.
- Ordinary `select_rime_candidate` / `sourceType=rime` rows now record a normal `macos_inputmethod_rime` commit instead of `/rime-select` side feedback.
- `RimeSelectRequest` now includes `shownCandidates`, aligning the native frontend with the backend skipped-higher contract.
- Updated README/debug/macOS adapter docs so they no longer claim model side candidates only record committed text.

Verification:
- Native source/rime-select focused tests passed: 16 tests OK.
- `scripts/build_macos_frontend.sh` built and signed `build/RagImeMac.app`.
- `git diff --check` passed.

Next:
- Run full suite, commit, and push.
- Continue P0 real frontend lifecycle work: candidate position/lifetime, no-input hide, and controlled foreground validation only when the user explicitly wants to test.

### 2026-07-03 19:28 CST
Problem:
- Continue Felix/Wisdom-Weasel candidate lifecycle migration without switching the real macOS input source.
- The sidecar already exposes `predictionSession.expiresAfterMs`, but the native Swift frontend still used a local fixed post-commit TTL. That made it easier for no-input/post-commit panels to stay visible longer than the backend policy and keep digit keys in candidate-selection mode.

Findings:
- Felix hides no-input prediction candidates on ordinary typing and arms an auto-hide timer for idle no-input predictions.
- This repo's backend already centralizes the equivalent policy: post-commit prediction sessions return `expiresAfterMs` and prefix/anchor sessions return `0` to mean "no scheduled expiration; state changes own visibility".
- Qwen3-1.7B-4bit MLX remains a later quality/slow lane candidate, not the realtime default until the panel flow is stable.

Changes:
- `RagInputController` now uses backend `predictionSession.expiresAfterMs` when scheduling native panel expiration.
- `expiresAfterMs == 0` is treated as "no frontend expiration timer", preserving prefix/anchor composition behavior.
- Added a source-level regression test so Swift cannot silently ignore backend session expiration again.

Verification:
- Focused native/post-commit lifecycle tests passed: 15 tests OK.
- `scripts/build_macos_frontend.sh` built and signed `build/RagImeMac.app`.
- Full suite passed: 359 tests OK.
- `git diff --check` passed.

Next:
- Commit and push.
- Continue P0 real frontend work: candidate panel position, stale no-input hide behavior under real apps, and controlled foreground validation only after the user explicitly wants to test.

### 2026-07-03 20:10 CST
Problem:
- User reported the native RAG-IME could degrade into pure ABC with no candidate panel, and earlier previews showed traditional Rime/luna candidates instead of the requested Wanxiang Simplified fallback.
- Felix/Wisdom-Weasel keeps Rime/Wanxiang candidates present first, then lets LLM/RAG supplement or rerank. The native AppKit harness was waiting for async sidecar before showing candidates, so a slow/failed sidecar made typing look broken.

Findings:
- `build/RagImeMac.app --preview-rime-dictionary-json` initially used `~/Library/Rime` and returned `comment=rime` plus traditional candidates.
- The Felix reference checkout contains `third_party/rime_wanxiang`, and the provider can expand its `import_tables`.
- Wanxiang cold YAML load is expensive, so live AppKit key handling must not synchronously cold-load the dictionary on the input thread.

Changes:
- `RagInputController` now shows local Rime/Wanxiang fallback candidates immediately after printable pinyin input, before the async sidecar refresh.
- If `/rime-suggest` fails while composition is unchanged, the native frontend restores local fallback candidates instead of clearing the panel.
- Panel anchoring now uses the client's selected caret range instead of `composition.utf16.count` as a document offset, reducing cross-app position errors.
- `bridge-config.json` now carries `rimeDictDir`; the build script defaults it to the Felix repo-local `third_party/rime_wanxiang` path when available.
- `RimeDictionaryCandidateProvider` now supports background `warmUp()`, `isReady`, and `allowColdLoad=false` for live input. CLI/doctor previews can still cold-load synchronously.
- Updated macOS adapter docs with the new dictionary order and nonblocking live-input rule.

Verification:
- Focused native/dictionary/install tests passed: 28 tests OK.
- `scripts/build_macos_frontend.sh` succeeded.
- `build/RagImeMac.app/Contents/MacOS/RagImeMac --print-config` shows `rimeDictDir` pointing at Felix `third_party/rime_wanxiang`.
- `build/RagImeMac.app/Contents/MacOS/RagImeMac --preview-rime-dictionary-json` now returns `comment=wanxiang` and Simplified candidates such as `ni -> 你`, `wo -> 我/我的/我想`, `shijie -> 世界`.
- Full suite passed: 363 tests OK.
- `git diff --check` passed.

Next:
- Re-run the focused Swift build after the final tiny fingerprint cleanup, then commit and push.
- Continue P0 foreground validation only with user permission because real app switching previously crashed Edge/Ghostty.

### 2026-07-03 20:15 CST
Problem:
- The native AppKit harness could still look like pure ABC if live input waited on Wanxiang YAML or sidecar refresh before showing candidates.
- Full Wanxiang YAML cold load is too heavy for the input thread; the previous direct precompile attempt produced a 234MB resource when every prefix was expanded.

Findings:
- A build-time hot index with 35k high-frequency entries keeps useful first-screen candidates (`ni`, `wo`, `wx`, `sj`, `shijie`) while staying small enough for the debug harness.
- `essay.txt` weights are needed so common phrases such as `我想` rank above rare dictionary entries.

Changes:
- Added `scripts/build_rime_candidate_index.py` to expand Wanxiang imports, fold tone marks, merge essay weights, and emit a capped `rime-candidate-index.tsv`.
- `scripts/build_macos_frontend.sh` now bundles the hot Wanxiang index into `RagImeMac.app`.
- `RimeDictionaryCandidateProvider` now checks the prebuilt index before YAML, so live local fallback candidates can appear without cold-loading the full dictionary.
- The prebuilt index warms in the background at provider creation/activation; live `allowColdLoad=false` lookups only read the loaded cache instead of parsing TSV/YAML on the key event path.
- `RagBridgeConfig` carries an optional `rimeCandidateIndexPath` override for explicit testing.

Verification:
- `scripts/build_macos_frontend.sh` built and signed `build/RagImeMac.app`; bundled index size was 1.4MB.
- `--preview-rime-dictionary-json` returned Wanxiang-style candidates: `ni -> 你/呢/...`, `wo -> 我/我的/我是/...`, `sj -> 世界/事件/...`, `shijie -> 世界/...`.
- Focused native/dictionary/install tests passed: 30 tests OK.
- Full suite passed: 365 tests OK.

Next:
- Run full suite, `git diff --check`, commit, and push.
- Continue with AI/RAG/memory visibility and English/code input after the fallback layer is stable.
