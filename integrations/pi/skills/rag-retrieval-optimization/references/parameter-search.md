# Parameter Search Playbook

Use this reference while defining a bounded offline search. The ranges below
are starting hypotheses, not recommended production defaults.

## Characterize first

Record:

- format mix, heading/page quality and parser failures;
- corpus documents, characters/tokens and expected update frequency;
- answer evidence size and whether one answer spans multiple passages;
- query language, length, entity density, ambiguity and multi-hop share;
- available local/remote embedding and rerank runtimes;
- latency, call, token, memory and disk budgets.

Choose chunking units that preserve the smallest complete evidence unit. Use a
chunk preview and inspect truncation, boundary loss and duplicated evidence
before indexing the full corpus.

## Parameter families

Search in this order so later stages do not compensate for a broken earlier
stage.

| Family | Initial bounded candidates | Inspect |
|---|---|---|
| parser | builtin, format-aware provider when authorized | missing text, tables, headings, page provenance |
| strategy | markdown/general/qa/book/laws/fixed as corpus permits | evidence split and unrelated content mixed together |
| chunk size | corpus-derived small/medium/large, often 400–1600 characters for a first pass | Recall@K, citation precision, index size |
| overlap | 0 plus roughly 10% and 20% of size, always below size | boundary recall versus duplicate hits |
| embedding | each available probed model with fixed chunking | fingerprint, dimensions, semantic slices, latency |
| retrieval mode | lexical, dense, hybrid | exact terms versus paraphrase and entity queries |
| fusion | normalized lexical/dense weights; RRF K candidates such as 20/60/100 | source dominance and stable ranks |
| candidates | 2x/4x/8x final K within budget | rerank headroom and latency |
| top K | task-derived values such as 3/5/8/10/20 | recall, context noise and answer grounding |
| threshold | score-distribution quantiles selected on validation | false evidence versus abstention |
| rerank | off/on, provider/model, candidate depth, final depth and timeout | MRR/nDCG gain per latency/token cost, fallback rate |
| Knowledge graph | Luna batch/concurrency/entity/relation caps; graph off/on, weights and bounded hops | relation/multi-hop gain, unsupported edges, fallback and noise |
| query strategy | original, rewrite, decomposition, multi-query | difficult slices and duplicate retrieval |

Do not grid-search every cross-product. Use successive stages or successive
halving: retain only hard-gate-passing candidates that improve the declared
validation objective, then explore the next family. Record pruned candidates
and the reason.

## Agent-callable validation search

Inside a run-owned `rag_benchmark` sandbox, establish the default profile with
one `evaluate_validation` call, then evaluate each bounded candidate against
the same host-registered suite ID. The operation returns aggregate metrics and
immutable hashes only. Treat `qrelsVisibleToAgent=false`,
`perCaseResultsVisible=false`, and `heldOutLabelsObserved=false` as required
integrity receipts rather than optional metadata.

Use `configure_base` for stored chunk/retrieval candidates. Rebuild only after
an index-affecting change, using the exact `rebuild_preview` token and revision.
The evaluation call's `mode`, `topK`, `threshold`, `rerank`, and
`rerankCandidateDepth` are controlled query-route overrides; other fusion and
graph settings come from the stored base profile. Select a winner by the
declared aggregate objective, deterministic tie-breakers, hard gates, and
budgets. Freeze it before an external harness observes held-out cases.

## Embedding comparisons

Compare models with identical corpus content, chunking, query set and retrieval
budget for the first pass. Probe one document and one query before a rebuild.
Record public provider/model identity, fingerprint, output dimensions, batch
behavior, timeout, vector coverage and peak resource use. Never record a raw
API key or assume equal score distributions across models; retune thresholds
on validation after the model changes.

Treat every embedding/chunking build as an immutable index generation. Build
the candidate beside the active generation, run the fixed validation suite,
then switch the active pointer only after acceptance. Retain the last-known-
good generation for bounded rollback. Never query a generation containing a
mixture of embedding fingerprints.

When the deployable dense backend is approximate (for example HNSW), keep a
deterministic exact-scan control over the same vectors. Select embedding,
fusion and rerank parameters against the exact control; then measure ANN
Recall@K loss, latency and repeated-build variance separately. Pin ANN build
and search settings in receipts. Do not report a small cross-run ANN delta as
a model or reranker gain when the exact control is unchanged.

## Agentic route search

Declare the finite route space before prompting: abstain/no-retrieval when the
contract permits it, stored-profile retrieval, lexical diagnostic, dense
diagnostic, hybrid retrieval, rewrite and bounded decomposition. Require a
structured receipt containing the selected route, unresolved evidence need,
queries issued, deduplicated evidence IDs and stop reason. A low-confidence
router uses the predeclared safe fallback rather than inventing a Tool or
parameter.

Compare route and loop policies on validation against the frozen tuned
single-call retriever. Select maximum queries, Tool calls, hops and context
budget before held-out. Retrieval qrels and answer labels are scorer-only and
must never appear in the router, planner, verifier or stopping prompt.

Keep the stages explicit: the first-stage union creates candidates; an
independent reranker scores the bounded query-candidate pairs; only then does
the Agent or subagent judge claim coverage and choose stop, rewrite,
decomposition or abstention. Compare `rerank off/on` with the Agent loop held
fixed before attributing a gain to Agentic reasoning.

For Luna Knowledge-graph extraction, search batch size and concurrency against
both throughput and tail latency. A batch that times out or falls back is not
an accepted candidate even if the resulting deterministic graph is queryable.
Cache by chunk content hash plus extractor fingerprint and report model chunks,
fallback chunks, errors and redacted request receipts.

## Agentic loop

Use a fixed maximum number of queries, Tool calls, retrieved chunks and tokens.
At each iteration:

1. state the unresolved evidence need;
2. generate a materially different rewrite or sub-question;
3. retrieve, independently rerank and deduplicate by base/document/chunk
   identity;
4. test sufficiency against the answer requirements from the reranked evidence;
5. answer with citations, continue within budget, or abstain.

Stop on sufficient evidence, repeated query/result state, exhausted budget,
scope rejection or authoritative Tool failure. Query-time iteration never
changes chunking, embedding or index configuration for a real base.
