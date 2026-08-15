---
name: alignment-and-decision
description: "Inspect available facts and settle material user-owned choices. Use when an unresolved decision would change scope, acceptance, authority, compatibility, cost, or observable behavior, or when the user explicitly asks to be grilled. Do not use for inspectable facts, reversible in-scope defaults, implementation planning, or routine confirmation; e.g., do not ask which test command to run when the repository already defines it."
---

# Align and Decide

Resolve uncertainty without turning inspectable facts or reversible defaults into questions.

## Workflow

1. Read the Session-provided request reference, corrections, constraints, and acceptance criteria.
2. Inspect available source, configuration, documentation, and runtime evidence before asking the user.
3. Separate facts, reversible defaults within current authority, external blockers, and material user-owned choices.
4. Apply a reversible default when it preserves the request. Ask only when the answer changes a material boundary.
5. Present the smallest independent question group in the user's language, with genuinely different options and a recommendation when evidence supports one.
6. When explicit Grill Mode is requested, challenge one material branch at a time and wait for the answer before continuing.
7. Record accepted decisions and their source references. Update the owned brief only when the decision materially changes shared understanding.

## Document Responsibility

- Update the current brief or decision section; do not create a parallel requirements document.
- Preserve the original request by reference. Append corrections instead of rewriting history.
- Include sources for derived facts and identify unresolved assumptions.

## Output

Return the common `AgentResult` envelope with:

```text
decisions | defaults used | remaining questions | inspected evidence
brief update receipt or proposed delta | residual uncertainty
```

Use `completed` when no material choice remains, `partial` when a user answer is required, and `blocked` only when a named external fact is unavailable.

## Not For

Do not plan implementation, execute changes, allocate Agents, invent approval, or ask the user for facts that can be inspected.

Example: when a repository already defines its verification command, inspect and run it instead of asking the user to choose one.
