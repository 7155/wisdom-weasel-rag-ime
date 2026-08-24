---
name: test-driven-implementation
description: "Implement one bounded known behavior change with regression protection. Use when the desired observable behavior, owning seam, and a meaningful executable check are known. Do not use for an unexplained failure, open-ended research, planning, or a change with no sensible test seam; e.g., localize an intermittent hang with systematic-debugging before starting a red-green cycle."
---

# Implement with Tests

Use one red-green cycle for one observable behavior. Evidence from this Skill is sufficient for the caller to integrate; no separate quality-gate Skill is required.

## Workflow

1. Read the TaskBrief, owning seam, acceptance criterion, compatibility limits, and relevant ContextRefs.
2. Trace the public behavior and confirm that the selected seam owns it. Return a planning suggestion if the seam is wrong or missing.
3. Write the narrowest meaningful check that fails because the requested behavior is absent, not because the environment or fixture is broken.
4. Implement the smallest coherent production change at the owning boundary.
5. Run the focused check, then proportional contract, integration, regression, and real-path checks. Record separately whether the implementation runs and whether the observed result satisfies the current precise requirement.
6. Preserve unrelated work and report every relevant check that was not run.
7. Update the owned worker document with changed behavior, files, red-green evidence, both verification axes, compatibility impact, and residual risk. Return failed acceptance to the supervising Agent with the responsible seam and next action; do not self-declare the whole Goal complete.

## Output

Return the common `AgentResult` envelope with:

```text
changed behavior and files | red evidence | green evidence
operability verdict | requirement-satisfaction verdict
proportional verification | compatibility impact | unrun checks | next action
worker-document update receipt or proposed delta | residual risk
```

## Not For

Do not loosen assertions to make a check pass, use production logic to generate the expected value, refactor unrelated code inside the cycle, or claim unverified surfaces.

Example: an intermittent hang with no localized owner needs `systematic-debugging`, not a guessed regression test around an arbitrary module.
