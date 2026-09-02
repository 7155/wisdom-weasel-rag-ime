# Authorized Repair And Verification

Read this only after the user explicitly confirms a candidate repair from the
web report.

1. Bind one repair owner, source fingerprint, failure reference, expected
   effect, and rollback target. Full-disk authority does not widen a
   multi-target report into permission to modify every target.
2. After the user's one-time confirmation, create an ordinary writable Agent
   Session with exactly this policy:
   - `mode: "coordinator"`
   - `toolProfileVersion: "control-center-auto-approve-v1"`
   - `executionMode: "full_trust"`
   - `dangerousModeConfirmation: "ENABLE_FULL_TRUST"`
   - `workspaceRoots: ["/"]`
   - `toolAllowlistMode: "profile"`
   - `projectContextEnabled: true`, `piSkillsEnabled: true`, and
     `codexSkillsEnabled: true`
   The paired profile directly auto-approves every Tool effect. It does not
   route actions through another approval Agent or ask for per-Tool approval.
   Persist the authorization as
   `writeAuthority: "auto_approved_full_trust"`. The diagnostic Session stays
   read-only.
3. Preserve the source fingerprint, failure reference, expected effect, test
   plan, and rollback target in the handoff.
4. Require a visible diff or configuration receipt and focused test evidence.
   A generated plan or handoff is still `candidate/unapplied`.
5. Re-run the same representative case in the Host-owned sandbox and persist
   the sandbox command receipt (or a registered vertical Connector
   `SandboxRun`), a new Trace, and a new Eval. The sandbox proof must show
   network blocked and remain bound to the repair Session/Trace; an exit code
   or assistant claim without that receipt is blocked evidence. Compare only
   when the cohort rules in `scoring-rubric.md` pass. A repair Trace whose
   input fingerprint or Eval suite differs from the source stays
   `incomparable`; display both absolute values and publish no delta.
   Trace diagnostic report v1 does not publish an `available` comparison:
   until a same-input, same-environment, same-suite, same-revision baseline is
   frozen, the report must remain `incomparable` or `unknown`.
6. Mark `applied` only from the change authority. Mark `verified` only after
   change receipt, test evidence, new Trace/Eval, and no material regression.
   Sandbox success is not install or foreground acceptance.
7. Keep the previous revision/configuration as the rollback target and report
   residual risk explicitly.

The report stores two separate linked facts: `repair_handoff` authorization
and repair verification. The first records the user's decision to enter a
system-wide, auto-approved full-trust repair Session; it is not an applied
change or verification receipt. The second may link only a server-issued
`TraceRepairReceipt` and Runtime-owned EvalRun. Each link appends a new immutable
report revision instead of rewriting the completed diagnostic result.
