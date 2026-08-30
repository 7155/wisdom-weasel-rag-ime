# Trace Diagnostic Scoring Rubric

Use this reference when a Trace report needs scores or comparisons. A score is
secondary to requirement completion and evidence authority.

## Eight Rows

| Dimension | Deterministic or ground-truth inputs | AI Judge may estimate |
| --- | --- | --- |
| Task completion | satisfied/expected requirements, tests, artifact/install/runtime receipts, explicit acceptance | ambiguous semantic acceptance only |
| Evidence and diagnosis | frozen required-evidence precision, recall, F1; evidence links; owner receipts | root-owner reasoning and alternative quality |
| Tool / Runtime | terminal success, schema error, timeout, avoidable identical retry, cancellation leakage, recovery time | whether an extra call was useful verification |
| Context | requirement recall, irrelevant/repeated/stale content, contradiction, compaction loss, reused Tool-result tokens | organization and sufficiency |
| Room collaboration | orphan/duplicate/conflicting scope, fan-out yield, unchanged review, avoidable serialization | whether multi-Agent use and decomposition were justified |
| Memory / RAG | Recall@K, MRR, nDCG, citation precision/recall, harmful injection, freshness, abstention | qualitative relevance when no labels exist |
| Efficiency | tokens, cost, wall clock, cache reads/writes, retries, cost per satisfied requirement | never infer waste without a comparable cohort |
| Repair quality | paired failing/passing case, change/test/new Trace/Eval receipts, regression count, rollback target | candidate repair plausibility before application |

## Semantic 0-3 Anchors

Use only with `authority: ai_judge_estimate`:

- `0`: the case visibly violates the dimension and evidence supports material harm.
- `1`: major defect; partial useful behavior exists but the core requirement is not reliable.
- `2`: mostly sound with a bounded weakness or meaningful uncertainty.
- `3`: strong for the observed scope; relevant alternatives and evidence are explicit.
- `null`: not applicable, unavailable, unknown, or not responsibly judgeable.

Always explain the anchor and cite inspection evidence IDs. Do not convert a
0-3 estimate into a deterministic percentage.

## Hard Gates

At minimum keep task completion and unsupported completion claims visible.
When a hard gate fails, the rollup is blocked even if some dimension scores are
high. When it is unknown, the rollup is unverified. `N/A` is excluded; unknown
is not silently excluded.

## Comparable Cohorts

Before claiming a delta, check workload/fixture, requirements, dataset and
label revision, model/provider/thinking, prompt/rubric, Tool/Skill profile,
workspace revision, instrumentation, and cost units. A declared treatment may
differ. If key fields are missing, label the comparison `unknown`; if they
differ materially, label it `incomparable`.
