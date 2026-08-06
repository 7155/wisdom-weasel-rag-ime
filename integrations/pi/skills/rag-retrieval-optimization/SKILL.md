---
name: rag-retrieval-optimization
description: Build and optimize Knowledge RAG pipelines when an Agent must create a knowledge base, inspect documents, choose parsing, chunking, embedding, lexical, dense, hybrid, graph, reranking, or Agentic retrieval behavior, rebuild indexes safely, and preserve rollback evidence; use evaluation only to validate changes, not for ordinary fact lookup or personal Memory.
---

# Knowledge RAG Flow Optimization

Turn a document collection into a usable, observable Knowledge retrieval
pipeline. Choose behavior from the corpus and query workload rather than
copying a tutorial's chunk size, weights, threshold or top K.

## Optimization Workflow

1. Establish ownership. Personal preferences, user facts, time-varying
   updates, conflicts and cross-session recall belong to the `memory` Tool.
   External or enterprise documents belong to the `knowledge` Tool. Never
   import Knowledge documents, chunks, graph edges or search feedback into
   personal Memory.
2. Define the operating goal before mutation: target Knowledge root/base,
   allowed sources, representative query types, freshness needs, citation and
   abstention requirements, latency/context limits, mutation authority and
   rollback point. Use a run-owned benchmark sandbox unless the user has
   authorized a real-base preview and approval flow.
3. Inspect the current system. Call `list_bases`, `get_base`,
   `list_documents` and `status`; record the exact `kbId`, revision, source
   identities, parser/chunk profile, retrieval profile, embedding fingerprint,
   index revision and readiness. Do not optimize a draft configuration that is
   not the active runtime state.
4. Map the corpus and workload. Identify languages, file and block types,
   headings/pages/tables/code, document-length distribution, answer
   granularity, exact identifiers, paraphrase queries, multi-part questions,
   multi-hop relations and update frequency. Read
   [rag-flow-optimization.md](references/rag-flow-optimization.md) to route
   each observed failure to the smallest useful technique.
5. Design intake before retrieval. Preserve stable source IDs, versions and
   hashes; normalize encoding and repeated furniture; retain headings, page or
   section anchors, table boundaries and provenance; deduplicate without
   deleting distinct versions. Reject silently empty or malformed parses.
6. Choose the evidence unit. Prefer structure-aware chunks when document
   structure is reliable and a bounded fixed-size fallback otherwise. Set
   chunk size from the expected answer unit and embedding/context limits; use
   overlap only for boundary loss. Consider contextual headers, parent/window
   expansion, semantic or proposition chunks only for a diagnosed need. Keep
   the strategy and provenance for every chunk.
7. Select the embedding profile. Probe provider/model availability, language
   coverage, required query/document prefixes, dimensions, fingerprint,
   latency and redacted failure before applying it. Compare embeddings with
   chunks and retrieval settings frozen. A fingerprint or dimension change
   creates a new immutable index generation and requires rebuild; old vectors
   never masquerade as the active index.
8. Configure first-stage retrieval. Use lexical search for names, codes and
   exact phrases; dense search for semantic or cross-lingual matches; use
   hybrid fusion when both contribute unique evidence. Tune candidate depth,
   lexical/dense weights, RRF K, top K and threshold as one bounded profile.
   Inspect per-channel hits before increasing complexity.
9. Shape the final evidence packet. Retrieve wide only when an independently
   configured reranker exists, then rerank narrow; deduplicate by
   source/chunk identity, preserve useful diversity, expand parents or
   neighbors only when needed, and pack evidence within the declared context
   budget. Record reranker provider/model/fingerprint, candidate depth, final
   depth, scores, timeout and fallback. Score the whole bounded candidate set
   before applying a per-source cap; truncating first lets repeated chunks from
   one document crowd out independent evidence. Any persistent score cache is
   local-only, fingerprint-bound and stores hash keys rather than query or
   passage text. A subagent cannot substitute for this
   stage: it plans queries and judges evidence sufficiency, while a reranker
   compares every bounded query-candidate pair under one scoring contract.
10. Apply safely. The Agent may create, import, configure, rebuild and clean
    only inside a run-owned sandbox. For a real Knowledge base, use the formal
    Tool preview, stop at `approvalRequired`, and apply only the exact approved
    revision, source hashes and embedding profile. Re-preview after any stale
    revision or changed impact.
11. Exercise representative queries and inspect traces. Keep a change only
    when it fixes its target failure without breaking citations, freshness,
    abstention, scope or resource limits. Otherwise restore the previous
    profile or index generation. Follow the Optimization Loop below; do not
    bundle unrelated changes into one unexplained improvement.
12. Add advanced routing last. The query-time order is first-stage lexical,
    dense or graph candidate generation, independent reranking, deduplication
    and packing, then Agent/subagent evidence sufficiency. Use bounded rewrite,
    decomposition and repeated retrieval only for queries the static route
    misses. Add Knowledge-graph expansion only for structural or relationship
    questions with provenance-preserving edges. Freeze query-time budgets and
    stop reasons; Agentic retrieval never reconfigures or rebuilds a real base.
    Before synthesis, build a compact claim-to-source evidence ledger: split
    every requested sub-item into atomic facts, preserve source names, values,
    dates, comparison directions and actions, and attach each fact only to
    directly supporting source IDs. Query only uncovered facts. The final
    answer covers every requested sub-item without lossy summarization, and
    its citations are the deduplicated union of the sources actually used.
    Treat open noun slots such as goals, measures, services, reasons, trends,
    effects, and questions using "which" or "what" as enumeration containers.
    Re-read the matching source sentence and its immediate neighbors, split
    every coordinated item, and retain all directly responsive qualifiers;
    never replace `A, B, C` with one broader label or stop after the first
    item. Before emitting the answer, run a coverage-only audit in question
    order: every slot must map to one or more supported ledger facts or to an
    explicit evidence-gap abstention. This audit reuses retrieved evidence and
    cannot consult references, qrels, scores, or new Tools.
    Prefer short, Tool-issued, case-scoped citation references such as `K1`
    over asking a model to transcribe opaque document IDs. Keep the same
    source-to-reference mapping across repeated searches for that case,
    resolve it deterministically back to an exact source ID, and fail closed
    on an unknown or ambiguous reference.
    Do not turn an unstated non-target premise into a whole-answer refusal: if
    evidence directly supports the requested fields and does not explicitly
    contradict the premise, answer those supported fields. Abstain or attach a
    conflict note only when the source explicitly conflicts or a core requested
    field lacks direct evidence.
    In an explicit high-quality Agentic mode, two independent retrieval roles
    may inspect every case before one parent verifier search. After the first
    synthesis, run exactly one fixed same-session coverage audit for every real
    case. It reuses the existing evidence, calls no Tool, performs no repeat
    delegation, never sees labels, references, qrels, or metrics, and preserves
    a complete answer unchanged when no slot is empty. Freeze and report this
    policy and retain both synthesis receipts. This is a deterministic
    degradation guard, not best-of-N answer selection.

## Optimization Loop

For each observed failure:

1. Capture the failing query, expected evidence shape, current Tool trace and
   active config/index fingerprints.
2. Form one falsifiable hypothesis and select one parameter family: intake,
   chunk/context representation, embedding, first-stage retrieval, reranking,
   packing, query policy or Knowledge graph.
3. Produce a typed candidate manifest and impact preview. Apply it only in the
   run-owned sandbox or through a fresh real-base approval.
4. Rebuild when parser, chunks, embedding or index-affecting configuration
   changes. Query-only settings do not justify a hidden rebuild.
5. Replay the representative probe suite. In a benchmark sandbox, call
   `evaluate_validation` and compare only its aggregate metrics and receipt;
   never request per-case qrels or labels. Retain or reject the candidate with
   a reason, then append receipts and failures before the next iteration.
6. Freeze the winning profile, active index generation and rollback target.

Read [parameter-search.md](references/parameter-search.md) when the candidate
space needs automated search rather than a few targeted probes.

Read [community-patterns.md](references/community-patterns.md) for the parts of
Yuxi and related community practice intentionally adopted here, plus the
technology-specific defaults this product intentionally does not copy.

## Benchmark Sandbox Optimization Workflow

Use `rag_benchmark` only when a local evaluation harness has explicitly bound
it to the current Session. The Tool is absent from the production catalog.

1. Call `create_run`, then `create_base` and `import_documents` with inline
   public or synthetic fixtures. Never pass a host path. Record the run, base,
   source hashes, initial config revision and usage limits.
2. Call `evaluate_validation` once on the host-provided validation suite ID to
   establish the default-profile baseline. The Tool returns aggregate
   Recall@K, MRR and nDCG plus immutable suite/receipt hashes; qrels, labels and
   per-case results remain hidden from the Agent.
3. Change one parameter family at a time. Use `configure_base` with the exact
   current revision. After parser, chunking, embedding or index-affecting
   changes, call `rebuild_preview` and then `rebuild` with its exact preview
   token, revision and `REBUILD` confirmation. Query-only changes do not need
   a rebuild. Use `graph_rebuild` only for a graph hypothesis.
4. Re-run `evaluate_validation` with the same suite ID and declared retrieval
   route. Prefer the hard-gate-passing candidate with the frozen objective;
   break metric ties deterministically by lower resource cost and then config
   hash. Record rejected candidates instead of silently forgetting them.
5. Stop at the declared evaluation/search/rebuild budget. Freeze the winner,
   config/index fingerprints and rollback target before any held-out run. The
   Agent must never receive a held-out suite ID, held-out labels, expected
   citations, reference answers or per-case scorer feedback.
6. Let the external harness run held-out scoring exactly once for an accepted
   experiment. It may publish aggregate and per-slice evidence after all Agent
   work is complete, but it never feeds the result back into tuning.
7. Call `status` to capture final runtime identity, then `cleanup` with
   `DELETE_BENCHMARK_RUN`. Cleanup is part of acceptance, including after a
   failed candidate or Provider call.

## Knowledge Graph Construction

The Knowledge graph is a derived index of Knowledge documents, never a Memory
graph. Build it only after source identity, parsing, chunks and citations are
stable.

1. In a run-owned benchmark sandbox, call `graph_rebuild` with extractor
   `luna`; accepted interview evidence pins `openai-codex/gpt-5.6-luna` and
   `max` thinking. Deterministic extraction is a diagnostic fallback and
   cannot support a Luna graph-effect claim.
2. Batch bounded chunks and cap concurrency, entities, relations and topics.
   Require exact in-chunk evidence for each entity and relation, normalize
   relation types, and discard unsupported nodes or edges.
3. Treat a timeout, missing chunk result, model fallback or mixed extractor
   fingerprint as a failed graph build. Preserve the private prompt/output log
   and publish only redacted request/hash receipts. Do not call a partially
   model-built graph successful.
4. Cache successful extraction by chunk content hash plus extractor
   fingerprint. Re-extract changed or failed chunks; remove obsolete graph
   nodes and edges by source identity.
5. Compare graph-disabled and graph-enabled routes on relationship and
   multi-hop validation slices. Enable graph only for query classes where it
   adds unique relevant evidence; direct dense/hybrid retrieval remains the
   fallback for ordinary single-hop fact lookup. Rank relation expansion with
   a bounded, receipt-visible personalized propagation from direct query
   concepts or independently measured high-confidence entity/triple matches.
   First-stage chunk concepts may be lower-weight support but cannot activate
   graph traversal by themselves. Record the activation decision, cap hops/
   nodes and preserve the evidence chunk on every traversed relation. Do not
   copy a community PageRank constant as a default.
6. For a real base, graph rebuild follows the same preview, approval, exact
   revision and rollback contract as other index mutations. The Agent may not
   silently create or replace a real graph during query-time retrieval.

## Product Knowledge Tool Workflow

Use the formal `knowledge` Tool for a real product knowledge base. Never call
the worker HTTP port or write its SQLite/files directly.

1. Inspect with `list_bases`, then `get_base`; preserve the exact `kbId` and
   `revision`. Use `list_documents` to confirm the current source set.
2. `create_base` accepts the name, description, `agentEnabled`, allowlisted
   parser, chunking config and retrieval config. It returns a native approval
   preview and performs no write before the matching approval is applied.
3. `import_text` accepts only an inline UTF-8 document up to 262144 bytes, a
   leaf `fileName`, `kbId` and exact `expectedRevision`. It never accepts a host
   path. Larger or binary files stay on the native file-picker/intake path.
4. `configure_base` requires the exact revision returned by `get_base`. It may
   change parser, visibility, chunk strategy/size/overlap, retrieval mode,
   top K, threshold, lexical/dense/graph weights, RRF K and candidate
   multiplier, `rerankEnabled` and `rerankCandidateDepth`. Before enabling
   rerank, inspect `status.reranker`: require `configured=true`, a non-empty
   provider/fingerprint, `independentStage=true`,
   `subagentSubstitute=false`, zero fallback and the intended model identity.
   The rerank candidate depth must be at least final top K and at most 100;
   reranked top K is capped at 20. A changed base invalidates an older pending
   approval. Model paths and revisions belong to the Knowledge Worker profile
   and never come from this Tool.
5. After a chunk/parser change, call `rebuild_preview`, then `rebuild` with the
   returned `configRevision`. Rebuild creates a second hash-bound approval and
   revalidates the worker preview at apply time.
6. To verify the stored profile, omit `searchMode`, `topK` and `threshold` from
   `search`; explicit query overrides are for controlled diagnostics. Product
   Agent reads cap final top K at 12 even if the management profile is wider.
   A diagnostic read may set `rerank` and `rerankCandidateDepth`; if rerank is
   requested but unavailable or malformed, stop on the explicit error rather
   than presenting the first-stage result as reranked. Confirm the returned
   `retrieval.reranker` identity and each hit's retrieval/rerank diagnostics.
   The benchmark-only `rag_benchmark` Tool owns wider experimental budgets
   inside its run root.

## Validation Boundary

Ordinary optimization uses representative queries, retrieval traces,
resolvable citations, freshness checks and rollback evidence. Do not turn every
Knowledge task into a benchmark.

When publishing an effect claim or comparing Skill/no-Skill, tuned or Agentic
lanes, read [evaluation-contract.md](references/evaluation-contract.md). That
separate workflow owns split isolation, frozen scorers, held-out runs, metrics
and numeric deltas; it validates this Skill's choices but does not define the
RAG construction workflow. Agent-visible `evaluate_validation` is aggregate
and validation-only; held-out scoring always stays outside the Agent Tool loop.

## Output Contract

Return the Knowledge base and document manifest, active parser/chunk profile,
embedding provider/model/fingerprint/dimensions, retrieval/rerank/packing,
Knowledge-graph extractor/model/fingerprint and Agentic settings, config and
index revisions, mutation/rebuild receipts,
representative query traces, retained and rejected changes, rollback target,
validation suite/receipt hashes and aggregate metrics, failures, unverified
runtime boundaries and exact next action. When an effect
claim was requested, attach the separate evaluation report; otherwise do not
invent a score.

## Self-Check

- Are Memory and Knowledge still independent in storage, indexes and Tools?
- Does the chosen parser and evidence unit match the actual corpus structure?
- Does the active embedding fingerprint match the rebuilt index generation?
- Did lexical and dense channel traces justify the selected retrieval mode?
- Is reranking an independently configured and traced stage rather than a
  prompt or subagent claim?
- Is the Knowledge graph Luna-built without fallback, evidence-grounded and
  enabled only on a validated query route?
- Are final chunks deduplicated, bounded and linked to resolvable sources?
- Does the claim-to-source evidence ledger cover every requested sub-item and
  preserve exact names, values, dates, directions and actions before answer
  synthesis?
- For every open noun slot, did the ledger expand the complete source
  enumeration instead of keeping only an umbrella summary or first item?
- Are real mutations covered by a current preview, approval and exact revision?
- Can the previous configuration and index generation be restored?
- Does every Agentic loop have a bounded call budget and explicit stop reason?
- Did the Agent tune only on aggregate validation results while held-out labels
  and per-case scorer feedback stayed outside the Tool loop?

## Boundaries

Do not write databases directly, expose credentials, download private corpora
into Git, mutate a real base without approval, hide a stale index behind a new
configuration, use enterprise documents as personal Memory, enable graph or
Agentic routing only to appear advanced, or claim that a public tutorial's
defaults are optimal for this corpus.
