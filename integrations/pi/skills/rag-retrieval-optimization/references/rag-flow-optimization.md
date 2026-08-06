# RAG Flow Optimization Playbook

Use this reference to choose the next pipeline change from the corpus and the
observed retrieval failure. It is an operational guide for building Knowledge
RAG, not a benchmark recipe.

## Corpus and workload map

| Corpus or query property | Start with | Add only when needed |
|---|---|---|
| manuals, policies, Markdown with stable headings | heading-aware chunks with heading path metadata | parent or neighbor expansion for cross-section answers |
| scanned or page-oriented reports | page-aware parsing with page anchors and OCR checks | layout/table parser when rows or reading order are lost |
| tables, catalogs and specifications | atomic table/row units plus surrounding title and schema | lexical boost for codes and exact values |
| source code or API references | symbol/section boundaries and path metadata | lexical-dense hybrid for identifiers plus intent |
| short homogeneous notes | bounded fixed-size chunks | small overlap only for demonstrated boundary misses |
| heterogeneous enterprise collection | strategy per document type with one fallback | intrinsic chunk signals to choose among approved strategies |
| exact names, SKUs, error codes or quotes | lexical candidates | dense union when explanatory paraphrases also matter |
| paraphrase, concept or cross-lingual questions | dense candidates from a language-matched embedding | hybrid union when exact entities must survive |
| multi-part or relationship questions | decomposition and repeated retrieval | graph expansion when explicit edges add unique evidence |

## Intake and normalization

1. Identify source, version, hash, language, document type and update policy
   before parsing.
2. Preserve titles, heading paths, pages, table labels, code symbols and other
   citation anchors. Strip repeated headers or navigation only when their
   identity is certain.
3. Detect empty extraction, encoding damage, broken reading order, duplicate
   versions and unexpectedly large blocks. Parser success means usable
   evidence with provenance, not merely a nonzero character count.
4. Keep raw-source identity separate from derived chunks. A reparse or rebuild
   creates a new generation without rewriting source history.

## Chunking and context representation

- Match chunks to the evidence unit a good answer cites. Smaller chunks tend
  to isolate facts; larger chunks retain narrative context but may dilute rank.
- Prefer heading, paragraph, page, table, symbol or other structural boundaries
  when trustworthy. Use a bounded token/character splitter as the deterministic
  fallback.
- Add overlap only after a boundary failure is visible. Excess overlap creates
  duplicate candidates and wastes final context.
- Prefix a compact contextual header when a chunk loses document, section or
  entity meaning out of context. Keep the original text and metadata so the
  transformation is auditable.
- Retrieve child chunks and expand to a bounded parent/window when ranking
  needs precision but answering needs surrounding context.
- Treat semantic, proposition and per-document adaptive chunking as candidate
  strategies for difficult or heterogeneous corpora. Persist the chosen
  strategy per chunk and keep an uncomplicated fallback.
- Useful intrinsic warnings include size-limit violations, low within-chunk
  cohesion, abrupt neighbor changes, broken block integrity and coreference
  breaks. They diagnose candidates; they do not prove retrieval quality.

## Embedding profile and migration

Record provider, model, version or fingerprint, dimensions, distance metric,
normalization, required query/document prefixes and language coverage. Probe
the exact runtime before configuration.

When comparing embeddings, freeze the corpus, parser, chunks and retrieval
settings. Re-embed into a new immutable index generation. Retune score
thresholds after a model or metric change because raw similarities are not
portable. Activate the new generation only after readiness checks; keep the
old generation as the explicit rollback target until acceptance.

## Retrieval stack

1. Inspect lexical and dense results separately. Lexical is the first route for
   exact strings; dense is the first route for semantic mismatch.
2. Use hybrid fusion only when the channels contribute complementary relevant
   candidates. Reciprocal-rank fusion is a stable default because it combines
   ranks rather than incomparable raw scores.
3. Candidate depth controls what later stages can recover. Increase it before
   blaming a reranker, but enforce a budget so recall cannot be gamed by
   returning most of the corpus.
4. Tune lexical/dense weights and RRF K from channel traces. Zero or nearly
   duplicate contribution means one channel may not justify its cost.
5. Apply score thresholds after fusion/reranking semantics are known. Always
   include not-found probes so a low threshold does not convert noise into an
   answer.

## Reranking and context packing

A reranker can reorder only the candidates it receives. If relevant evidence
is absent from the candidate union, repair intake, chunks, embedding or
first-stage retrieval first.

Do not use an Agent or subagent as an unnamed reranker. A reranker receives a
bounded query and candidate set and returns comparable scores/order under a
recorded provider/model/fingerprint. The Agent consumes that ordered evidence
to identify missing claims, rewrite or decompose queries, stop or abstain.

Retrieve a bounded wider set, rerank to a smaller set, deduplicate repeated
chunks, preserve source or subtopic diversity, and then expand only the parent
or neighbors needed to answer. Score before diversity truncation: keep the
highest-ranked passage from each source, then fill the remaining budget from
lower-ranked unique sources. Pack evidence by answer coverage and context
budget rather than by top K alone. Keep each packed span linked to its original
source anchor and retrieval/rerank scores.

## Agentic and graph retrieval

Use structured query policies, not unconstrained free-form wandering:

1. classify whether the query is exact, semantic, ambiguous, multi-part or
   relationship-heavy;
2. select static search, rewrite, decomposition or multi-query retrieval;
3. execute bounded searches and deduplicate evidence across rounds;
4. for a multi-part question, keep a small claim-to-source coverage map: split
   the requested answer into atomic items, mark which returned source directly
   supports each item, and query only the missing items; never treat one
   relevant-looking passage as proof that every subquestion is covered;
5. decide `sufficient`, `not_found` or `needs_one_more_query` from returned
   evidence; `sufficient` requires every answer item to have at least one
   resolvable source, while `not_found` remains a valid outcome;
6. stop on sufficiency, repeated evidence, no new evidence or the call budget.

Graph construction and expansion belong to Knowledge and must preserve source
provenance. In accepted benchmark builds, Luna extracts bounded entities and
relations from each chunk with exact evidence; unsupported values are removed,
and any timeout, absent result or deterministic fallback rejects the Luna
claim. Cache successful extraction by content hash and extractor fingerprint.
At query time, compare direct retrieval with graph-added evidence on
relationship and multi-hop queries; keep graph off for query classes where it
adds only noise. Do not reuse the personal Memory graph, lifecycle or conflict
rules as a Knowledge graph shortcut. Activate relation traversal only from a
direct query-concept match or a separately measured high-confidence entity/
triple match. First-stage chunk concepts may provide lower-weight support but
must not independently activate graph traversal: a 12-query Chinese diagnostic
showed that broad first-stage activation severely degraded nDCG. Use a bounded
personalized rank over evidence-grounded edges. Record the activation decision,
seed source/weight, algorithm, restart, iterations, hop/node caps and expansion
count so graph results can be reproduced.

## Freshness and index lifecycle

- Bind each index generation to source hashes, parser/chunk config, embedding
  fingerprint and retrieval-relevant schema revision.
- Mark a generation stale when any bound input changes. Never show a saved
  draft as the active runtime state.
- Build and verify a replacement generation before activation when possible.
  Activation and rollback should be explicit, atomic and observable.
- On document deletion or replacement, remove stale chunks and graph edges by
  source identity, then verify that old evidence is no longer retrievable.

## Failure map

| Observed trace | Likely next action | Avoid |
|---|---|---|
| parsed document has no usable blocks | repair parser/OCR and anchors | changing top K |
| correct source exists but fact is split | adjust boundary, overlap or window | globally enlarging every chunk |
| exact identifier is missed | lexical or hybrid candidate union | assuming a newer embedding fixes it |
| paraphrase is missed while exact search works | compare dense profiles with chunks frozen | changing embedding and chunks together |
| relevant candidate is present but buried | increase bounded candidate depth, then rerank | expecting rerank to create missing evidence |
| final context contains duplicates | identity deduplication and diversity packing | raising top K again |
| correct evidence is rejected | retune threshold for the active score semantics | carrying a threshold across embeddings |
| stale result survives replacement | repair source/index invalidation | prompt-level warnings |
| multi-part question is partially answered | decompose and retrieve missing subquestion | one broad rewrite loop |
| graph adds unrelated neighbors | restrict edge/type/hop policy or disable graph | using graph for every query |

## Agent-driven optimization

Expose typed candidate manifests rather than unrestricted source editing. The
Agent may inspect, create, import, configure, rebuild and query a run-owned
sandbox; it records every proposed profile, receipt, trace, failure, keep or
rollback decision in an append-only ledger. It cannot edit the scorer, conceal
failed runs, read private host paths, mutate a real Knowledge base without a
fresh approval, or enable external telemetry/uploads.

Automated search should follow the same flow: diagnose a failure, search one
bounded parameter family, rebuild only when required, promote a candidate,
then freeze the selected profile. The online Agentic query loop consumes that
profile; it does not self-modify the index or configuration.

## Verification

Use representative probes during ordinary pipeline work. If the result will
be presented as a measured improvement, move the fixed pipeline into the
separate evaluation workflow in `evaluation-contract.md`: freeze data splits,
scorer, budgets and config before held-out reporting. Evaluation confirms the
optimization; it is not the Skill's primary workflow.
