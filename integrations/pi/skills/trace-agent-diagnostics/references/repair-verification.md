# Authorized Repair And Verification

Read this only after the user explicitly confirms a candidate repair from the
web report.

1. Bind one repair owner and exact authorized workspace roots. A multi-target
   report does not authorize modifying every target.
2. Create an ordinary writable Agent Session under the normal per-action
   approval boundary. The diagnostic Session stays read-only.
3. Preserve the source fingerprint, failure reference, expected effect, test
   plan, and rollback target in the handoff.
4. Require a visible diff or configuration receipt and focused test evidence.
   A generated plan or handoff is still `candidate/unapplied`.
5. Re-run the same representative case and persist a new Trace/Eval. Compare
   only when the cohort rules in `scoring-rubric.md` pass.
6. Mark `applied` only from the change authority. Mark `verified` only after
   change receipt, test evidence, new Trace/Eval, and no material regression.
   Sandbox success is not install or foreground acceptance.
7. Keep the previous revision/configuration as the rollback target and report
   residual risk explicitly.
