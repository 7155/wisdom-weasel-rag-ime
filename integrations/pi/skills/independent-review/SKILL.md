---
name: independent-review
description: "Independently review a fixed result, diff, artifact, or evidence set against the original request and project standards. Use when the user requests a distinct review or risk warrants a separate reviewer. Do not use as a mandatory gate, for self-review, active diagnosis, or implementation; e.g., an author checking their own small diff performs normal verification instead of claiming independent review."
---

# Review Independently

Review a fixed scope without relying on the author's conclusion and without modifying the reviewed work.

## Workflow

1. Read the request reference, acceptance criteria, fixed review target, evidence refs, and applicable repository guidance.
2. Stop without a verdict when the scope or fixed point cannot be resolved.
3. Reconstruct expected behavior independently from the source material.
4. Inspect the complete relevant effect, including downstream consumers and state transitions.
5. Review requirement fidelity separately from code or artifact quality.
6. Reproduce material evidence and probe risk-shaped negative paths proportional to the change.
7. Report only actionable, evidence-backed findings. Keep optional improvements separate from defects.
8. Write the review document when one is assigned, or return a proposed review delta.

## Output

Return the common `AgentResult` envelope with:

```text
verdict: clear | clear_with_risk | changes_required
requirement findings | quality findings | evidence
required fixes | optional improvements | residual risk
review-document update receipt or proposed delta
```

## Not For

Do not modify reviewed work, self-review authored changes, manufacture a defect from preference, allocate repair work, or emit the caller's final result.

Example: the Agent that authored a change may verify it, but a genuinely independent verdict must come from a different fixed-scope reviewer.
