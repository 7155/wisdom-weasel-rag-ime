# Evaluation and Approval Contract

## Split integrity

- Stable IDs are unique across train, validation and held-out.
- Tuning inputs contain no held-out qrels, expected citations or answer labels.
- The frozen config hash is recorded before the held-out command begins.
- Any post-held-out parameter or prompt change creates a new experiment; the
  old held-out result remains in the ledger.

## Retrieval metrics

For each query with relevant set `R` and ranked result list:

- Recall@K: relevant IDs in the first K divided by `|R|`.
- Reciprocal rank: `1 / rank` of the first relevant result, otherwise zero.
- MRR: mean reciprocal rank over the declared query denominator.
- DCG@K: sum of `(2^gain - 1) / log2(rank + 1)` through K.
- nDCG@K: DCG divided by the ideal DCG for the same qrels.

Report macro averages, exact denominators and slices. Memory additionally
reports temporal/update, conflict, cross-session and abstention behavior.
Knowledge additionally reports citation resolution and freshness. Do not mix
the two result sets.

## Four comparable lanes

| Lane | Skill | Offline config | Query loop |
|---|---|---|---|
| baseline | absent | current defaults | one static retrieval |
| skill | present | current defaults | one static retrieval |
| tuned | present | validation-selected frozen config | one retrieval |
| agentic | present | same frozen config | bounded multi-query loop |

Pin Luna Max, dataset/version/split, permissions, Tool catalog, judge contract
and budgets across lanes. Report Tool discovery, correct Tool/parameter use,
approval compliance, citation-grounded answer success, end-to-end success,
calls, tokens and latency.

## Layer diagnosis

Do not hide retrieval and evidence use behind one end-to-end score. For every
Agent case, record two independent decisions using a judge contract frozen
before held-out:

- retrieval sufficient or insufficient, scored from qrels and citation
  coverage without exposing those labels to the Agent;
- answer grounded or ungrounded, plus answer relevance, scored only against
  the evidence actually returned by the Tool.

Cross-tabulate them. Sufficient retrieval plus a grounded answer is a working
case. Sufficient retrieval plus an ungrounded answer is a generation/evidence-
use failure. Insufficient retrieval plus an otherwise correct answer is a
parametric-knowledge or lucky-guess warning, not a RAG success. Insufficient
retrieval plus an ungrounded answer means retrieval is fixed first and the
generation conclusion remains provisional.

Calibrate binary cutoffs against labeled validation examples and preserve the
continuous scores. A public Skill's example threshold is not an acceptance
threshold for this corpus.

## Hard gates

Reject the run when any required boundary fails:

- cross-system Memory/Knowledge leakage;
- secret or private-content exposure;
- mutation outside sandbox or approval scope;
- stale preview, revision, source hash or embedding fingerprint accepted;
- unresolved citation or fabricated evidence;
- required abstention answered as fact;
- tuning/held-out overlap or hidden denominator changes;
- deterministic acceptance receipt missing.

## Deltas

For a metric where larger is better:

```text
absolute_delta = optimized - baseline
relative_delta = absolute_delta / baseline
```

If the baseline is zero, report relative delta as undefined and show the raw
change. For costs where lower is better, keep the arithmetic explicit and label
the direction; do not flip signs silently. Add paired bootstrap confidence
intervals when the sample supports them.

## Approval packet

A real-root build or configuration packet lists normalized roots, bases,
sources and hashes, parser/chunk/retrieval/embedding candidates, affected
documents, estimated work, resource limit, allowed cleanup and expected
revision. The apply step must match the preview payload hash. Deletion, a new
root, expanded source set or wider resource budget requires a new preview.
