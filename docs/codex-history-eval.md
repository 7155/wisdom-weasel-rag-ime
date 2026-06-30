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
- Compare local FTS5, embedding recall, rerank, and VCP-style context cache hit behavior on the same cases.
