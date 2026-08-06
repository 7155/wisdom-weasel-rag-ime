# Community Patterns Adopted Selectively

Community projects are method sources, not parameter authorities. Reproduce
the mechanism inside this product's typed Tool, approval, provenance and
evaluation boundaries, then choose parameters from this corpus's validation
data.

## Yuxi

Source snapshot inspected 2026-08-05 at revision
`c765d90455fe52a864cfe8e4bd89d26d6862bb01`:
[xerrors/Yuxi](https://github.com/xerrors/Yuxi). Its public design combines
permission-filtered Knowledge tools, format-aware chunk presets, unified
Embedding/Rerank identities, citations, entity/relation graph construction,
bounded subgraph retrieval and Agent/subagent orchestration. These are useful
separations of responsibility.

Adopt these mechanisms:

- keep first-stage retrieval, reranking and Agent reasoning as separate traced
  stages;
- bind Skill activation to a declared Tool dependency set, but re-check the
  user's visible Knowledge bases at execution time; Skill visibility never
  grants access to a resource;
- expose Search, file discovery, in-document Find and bounded Open as distinct
  operations so the Agent can move from broad recall to exact source context
  without stuffing entire documents into one Tool result;
- choose a structure-aware chunk route from the actual document class, such as
  general prose, QA, books, policies/laws or a strict separator, while keeping
  one deterministic fallback and recording the chunk engine version;
- resolve Embedding and Rerank through one model registry/fingerprint boundary
  and reject stale indexes or caches when that identity changes;
- let the Agent decide whether evidence is sufficient and issue a bounded,
  materially different follow-up query when it is not;
- preserve resolvable citations through retrieval, reranking and answer use;
- derive a Knowledge graph from evidence-grounded entities and relations, then
  retrieve a bounded subgraph only for relation or multi-hop questions;
- treat query entity/triple similarity as the primary graph seed signal;
  Yuxi's first-stage chunk entities are a lower-weight supplemental signal,
  not evidence that every retrieved chunk should activate graph expansion;
- cap relation traversal, apply personalized propagation from explicit seed
  weights, return evidence chunks rather than naked graph nodes, and fuse the
  result with direct retrieval by a traced rank-fusion stage;
- evaluate retrieval routes and graph contribution independently before using
  end-to-end answer scores.

Adapt them to this product:

- use the existing Knowledge Tool, SQLite/FTS and configured dense-index
  boundary instead of introducing a second knowledge-base owner;
- preserve this product's preview, revision, approval and rollback receipts for
  management operations; Yuxi's read-oriented built-in Skill is a method
  reference, not authority to bypass our mutation contract;
- use Luna Max for benchmark graph extraction with hash-bound receipts,
  bounded batches, cache keys and observable fallback;
- keep Memory storage, indexing, Tools, conflict/update semantics and metrics
  entirely separate;
- require sandbox ownership for automatic mutation and preview/approval for a
  real Knowledge base.

Do not copy these as assumed improvements:

- Milvus, Neo4j, LangGraph or another framework merely because the reference
  project uses it;
- a public default chunk size, overlap, fusion weight, top K, threshold,
  reranker depth, graph hop count or PageRank damping factor;
- graph expansion for every query;
- a subagent in place of a reranker;
- Yuxi's binary answer judge or optional headline score as a replacement for
  this product's MRR/nDCG, citation, refusal and layer-diagnosis metrics;
- a public demo result as evidence for this product.

Every retained choice needs a local config fingerprint, trace, validation
result and rollback target. Every rejected choice stays in the experiment
ledger with its failure reason.
