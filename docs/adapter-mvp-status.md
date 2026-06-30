# Adapter MVP Status

## What This Commit Proves

This repo now has an input-method adapter layer and a local SQLite/FTS5 CoreClient that can run without cloud models.

It proves:

- RAG results can be candidateized into short input suggestions.
- committed input events are written into local SQLite;
- FTS5 retrieval returns personal memories;
- `SuggestionCompiler` is an explicit IME adapter layer between retrieved memory and candidate UI.
- Evidence preview and expanded evidence can be shown separately.
- Candidate actions can be wired back to a core client.
- delete/pin/downrank actions persist and change later ranking;
- Background RAG refresh can be gated by idle time, punctuation, explicit request, and privacy blockers.
- Agent first-run memory injection can be built from the same core client.
- Three realistic UI scenarios can be rendered and checked by scripts.
- A macOS InputMethodKit shell can compile into `RagImeMac.app`.
- The Swift frontend can call the Python local backend through `suggest-json`.

## What It Does Not Prove Yet

The full product goal still requires the shared core to expose stable persistence and retrieval APIs.

Not yet proven here:

- shared core CLI/import wiring against the PI memory database;
- end-to-end test against the future PI shared core.

The fixture client is intentionally deterministic and local. It is only for adapter/UI unit tests. The acceptance script uses the local SQLite/FTS5 backend.

## Acceptance Commands

```bash
python3 -m rag_ime.cli seed-demo --reset
python3 -m unittest discover -s tests
python3 -m rag_ime.cli demo --top-k 3
python3 scripts/acceptance.py
python3 -m rag_ime.cli action-demo
python3 -m rag_ime.cli agent-hook --top-k 3
scripts/build_macos_frontend.sh
build/RagImeMac.app/Contents/MacOS/RagImeMac --preview-json
```

## Three UI Scenarios

### 1. 写面试项目介绍

Input:

```text
我这个项目的亮点是
```

Expected short candidates:

- 高频实时场景里的个人记忆系统
- 默认本地完成, 不上传个人输入历史
- 用户选择候选会反向校准记忆源

### 2. 写技术方案

Input:

```text
SQLite 和 FTS5 第一版
```

Expected short candidates:

- 先用 FTS5 证明召回收益
- 排序先用规则分数, 再接轻量 reranker
- 默认本地完成, 不上传个人输入历史

### 3. 输入项目专有名词/固定表达

Input:

```text
Agent 首次运行
```

Expected short candidates:

- 生成 PROJECT_MEMORY_BLOCK
- 把本地记忆注入 Agent 首次运行上下文
- 高频实时场景里的个人记忆系统

## Future Shared Core Integration Gate

Before replacing the local MVP backend with the shared core, verify:

```text
committed text
  -> shared core record_event
  -> SQLite/FTS5 persistence
  -> shared core suggest_for_input
  -> InputSuggestion rendering
  -> apply_action
  -> later ranking changes
  -> buildAgentContextInjection
```
