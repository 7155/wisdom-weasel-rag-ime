# Codex History Import And Retrieval Evaluation

RAG-IME needs a real personal-memory benchmark, not only toy demo memories. The first local benchmark source is Codex history because it contains dense project decisions, repeated wording, user preferences, and long-running implementation context.

This workflow is local-only. It never uploads Codex logs. The user must pass an explicit path before anything is parsed.

## Import Shape

Codex history is treated as committed text evidence:

```text
Codex JSONL
  -> text fragments from message/content/text/summary/objective fields
  -> InputEvent(source="codex_history", schema_id="codex_history", app="codex")
  -> local SQLite + FTS5 memory store
  -> same suggestion/action/agent-hook path as normal IME input
```

This keeps the benchmark aligned with the product: the input method and PI extension can share the same core API instead of building separate memory databases.

## Dry Run

Preview parsed records without writing the database:

```bash
python3 -m rag_ime.cli import-codex-history \
  --path "$HOME/.codex/session_index.jsonl" \
  --dry-run \
  --limit 20
```

For a directory of JSONL files:

```bash
python3 -m rag_ime.cli import-codex-history \
  --path "$HOME/.codex" \
  --dry-run \
  --limit 50
```

When the path is a directory, the CLI reads newest modified session files first by default:

```text
--path-order mtime-desc
```

Use `--path-order path` only when you need deterministic path-sorted replay. The importer also filters common Codex runtime noise before records become memories: developer/system prompts, `AGENTS.md` injections, environment/sandbox blocks, tool call output, token-count events, and encrypted reasoning payloads are not treated as user memory. The goal is to learn user requirements, project decisions, assistant summaries, and final explanations, not shell transcripts or system context.

The output includes only short samples so private logs are not dumped into the terminal.

## Real Import

Import a bounded slice into the local RAG-IME DB:

```bash
python3 -m rag_ime.cli --db-path .rag-ime-data/rag-ime.sqlite \
  import-codex-history \
  --path "$HOME/.codex/session_index.jsonl" \
  --project wisdom-weasel-rag-ime \
  --limit 500
```

Each imported record receives tags:

```text
codex-history
role:<role when available>
record:<stable hash prefix>
```

The import command uses `record:<stable hash prefix>` to skip duplicate records by default. Use `--allow-duplicates` only when intentionally replaying a corpus.

## Evaluation Cases

Create a JSONL case file:

```jsonl
{"id":"squirrel-rag","query":"Squirrel RAG 输入法候选","expectedTerms":["Squirrel","本地记忆"]}
{"id":"agent-hook","query":"首次运行自动注入背景记忆","expectedTerms":["PROJECT_MEMORY_BLOCK"]}
{"id":"dirty-pinyin-boundary","query":"为什么不能让大模型直接预测脏拼音","expectedTerms":["Rime","拼音解析"],"forbiddenTerms":["让大模型直接解析脏拼音"]}
```

Run:

```bash
python3 -m rag_ime.cli --db-path .rag-ime-data/rag-ime.sqlite \
  eval-codex-history \
  --cases-file docs/eval/codex-history-cases.example.jsonl \
  --top-k 5 \
  --match any
```

Use `--match all` for stricter cases where every expected term must appear in the same top-K suggestion surface/evidence. Terms split across several suggestions no longer count as an all-match hit, because the input method user chooses one candidate at a time.

Use `--repeat N` to replay the same cases in one process and measure cold/warm cache behavior:

```bash
python3 -m rag_ime.cli --db-path .rag-ime-data/rag-ime.sqlite \
  eval-codex-history \
  --cases-file docs/eval/codex-history-cases.example.jsonl \
  --top-k 5 \
  --repeat 3
```

When `--repeat` is greater than 1, per-case ids are suffixed as `#r1`, `#r2`, and so on. This avoids latency/result overwrites while keeping the original query, context, project, and expected terms identical. The report adds:

```json
{
  "repeat": {
    "requested": 3,
    "baseCaseCount": 20,
    "effectiveCaseCount": 60
  }
}
```

Compare `latency` and `cacheStats` between `--suggestion-cache-size 0` and the default cache to check whether repeated short IME queries actually benefit from the local cache.

The report keeps the original `passed` / `passRate` fields and adds ranking metrics:

```json
{
  "metrics": {
    "hitRate": 0.8,
    "top1Accuracy": 0.5,
    "meanReciprocalRank": 0.65,
    "meanFirstMatchRank": 1.75,
    "noiseRate": 0.1
  }
}
```

When `--core-mode local` is used, the report also includes process-local cache stats:

```json
{
  "cacheStats": {
    "enabled": true,
    "hits": 4,
    "misses": 8,
    "hitRate": 0.3333333333333333,
    "invalidations": 0
  }
}
```

Use `RAG_IME_SUGGESTION_CACHE_SIZE=0` or `--suggestion-cache-size 0` to benchmark uncached retrieval.

## Optional Vector Side Index

The local SQLite core can maintain a side table of vectors next to the FTS5 index. This is disabled by default so the real input-method path stays fast and dependency-free until an embedding provider is explicitly configured.

Backfill existing memories with the deterministic local baseline:

```bash
python3 -m rag_ime.cli --db-path .rag-ime-data/rag-ime.sqlite \
  --embedding-provider local-hash \
  rebuild-vector-index \
  --project wisdom-weasel-rag-ime
```

`local-hash` is not a semantic embedding model. It is a local term-vector baseline used to test the storage, merge, scoring, and evaluation contract before connecting a real embedding service.

For a real semantic model running on the Mac or a user-owned WSL notebook:

```bash
export RAG_IME_EMBEDDING_PROVIDER=openai-compatible
export RAG_IME_EMBEDDING_BASE_URL=http://127.0.0.1:8000
export RAG_IME_EMBEDDING_MODEL=bge-small-zh

python3 -m rag_ime.cli --db-path .rag-ime-data/rag-ime.sqlite \
  rebuild-vector-index \
  --project wisdom-weasel-rag-ime
```

Relevant knobs:

- `RAG_IME_EMBEDDING_TIMEOUT_MS`: per-request embedding timeout, default `800`.
- `RAG_IME_EMBEDDING_DIMENSIONS`: optional dimensions field for providers that support it.
- `RAG_IME_VECTOR_CANDIDATES` / `--embedding-vector-candidates`: vector rows merged into retrieval, default `80`.
- `RAG_IME_VECTOR_WEIGHT` / `--embedding-vector-weight`: similarity score multiplier, default `1.4`.

When vector recall is enabled, eval reports include:

```json
{
  "vectorStats": {
    "enabled": true,
    "providerFingerprint": "openai-compatible:bge-small-zh",
    "totalVectors": 500,
    "activeProviderVectors": 500,
    "candidateLimit": 80,
    "weight": 1.4
  }
}
```

Use the same case file to compare FTS-only and vector-hybrid behavior:

```bash
python3 -m rag_ime.cli --db-path .rag-ime-data/rag-ime.sqlite \
  eval-codex-history \
  --cases-file docs/eval/codex-history-cases.example.jsonl \
  --top-k 5 \
  --repeat 3

python3 -m rag_ime.cli --db-path .rag-ime-data/rag-ime.sqlite \
  --embedding-provider openai-compatible \
  eval-codex-history \
  --cases-file docs/eval/codex-history-cases.example.jsonl \
  --top-k 5 \
  --repeat 3
```

The goal is not only higher hit rate. For an input method, vector recall must improve `top1Accuracy` / `meanReciprocalRank` without making `latency.p95Ms` too high for candidate refresh.

The eval command also records end-to-end per-case latency for the actual adapter call:

```json
{
  "latency": {
    "caseCount": 20,
    "totalMs": 123,
    "avgMs": 6.15,
    "p50Ms": 4,
    "p95Ms": 18,
    "maxMs": 21
  },
  "cases": [
    {"caseId": "squirrel-rag", "elapsedMs": 4}
  ]
}
```

This is intentionally measured around `adapter.suggest(...)`, so it includes core retrieval, cache lookup, ranking, and suggestion compilation. It does not include local LLM prediction unless the eval path is extended to call the model lane.

Per-case fields include:

- `firstMatchRank`: first candidate rank that satisfies `--match`;
- `reciprocalRank`: `1 / firstMatchRank`, or `0` when no candidate hit;
- `top1Passed`: whether the first visible suggestion already matched;
- `termFirstRanks`: where each expected term first appeared;
- `forbiddenMatchedTerms`: noise terms found in returned suggestions. If any forbidden term appears, the case fails even if expected terms matched.
- `elapsedMs`: end-to-end adapter suggestion time for that case.

## Compare RAG Against Model Prediction

After configuring a local model with `RAG_IME_PREDICTOR_*`, run the same case file through both the RAG lane and the model prediction lane:

```bash
python3 -m rag_ime.cli --db-path .rag-ime-data/rag-ime.sqlite \
  eval-comparison \
  --cases-file docs/eval/codex-history-cases.example.jsonl \
  --top-k 5 \
  --max-candidates 3 \
  --match any \
  --repeat 2
```

The report shape is:

```json
{
  "schemaVersion": "rag-ime.eval-comparison.v1",
  "rag": {
    "metrics": {"top1Accuracy": 0.7},
    "cacheStats": {"hitRate": 0.5}
  },
  "model": {
    "metrics": {"top1Accuracy": 0.4},
    "prediction": {
      "providerConfigured": true,
      "overBudgetCount": 1
    }
  },
  "comparison": {
    "bothPassed": 6,
    "ragOnlyPassed": 3,
    "modelOnlyPassed": 1,
    "neitherPassed": 2,
    "winnerByPassRate": "rag",
    "winnerByTop1Accuracy": "rag"
  }
}
```

This is the main full-flow gate for deciding whether a local Qwen/MLX/llama.cpp endpoint is actually useful in the IME. A model that is fast but only passes cases already covered by RAG is not enough reason to enable the model lane by default. A model that wins `modelOnlyPassed` cases but exceeds the sidecar latency budget should stay debug-only until the provider gets faster.

## Why This Matters

Traditional RAG evaluation often asks whether a document chunk was retrieved. For an input method, the better question is:

```text
When the user is typing a short intent, does the candidate panel surface the prior wording,
decision, constraint, or project memory that the user would actually choose?
```

This is why the evaluation checks the final suggestions rather than only raw FTS rows.

Candidate-level ranking matters more than raw recall. A memory that appears at rank 5 is technically retrieved, but the user is unlikely to select it during typing. `meanReciprocalRank` and `top1Accuracy` make that visible while keeping the evaluation local and deterministic.

## Next Improvements

- Add leave-one-session-out evaluation from Codex logs.
- Add latency buckets so retrieval quality and input-method responsiveness are measured together.
- Compare local FTS5, real embedding recall, rerank, and VCP-style context cache hit behavior on the same cases.
