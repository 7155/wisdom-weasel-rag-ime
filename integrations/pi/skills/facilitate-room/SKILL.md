---
name: facilitate-room
description: "Coordinate a Room as a lightweight composition of ordinary Partner Sessions. Use when, and only when, the current Session is the designated Room Facilitator responsible for shared alignment, delegation, integration, optional review, and one final result. Do not use in a standalone Session, Room Partner, Reviewer, or private Tool Agent; e.g., a Partner fixing one bounded file uses a task Skill rather than Room facilitation."
---

# Facilitate a Room

Keep the Room lightweight. Partners remain ordinary Sessions and use the same task Skills as any other Session.

## Workflow

1. Read the project, outcome, Room brief, current workboard, and Runtime participant projection.
2. Clarify material user choices only when necessary. Use planning only when the work truly needs multiple items or owners.
3. Keep one coherent responsibility in the Facilitator when delegation would not help.
4. Delegate bounded Partner tasks with objective, scope, acceptance, exact ContextRefs, exact SkillRefs, workspace binding, capabilities, and expected output.
5. Let each Partner choose private Session subagents within its granted capabilities.
6. Consume Partner progress and result events. Publish only material shared progress and resolve dependencies or conflicts from evidence.
7. Integrate Partner results into the authoritative workspace and shared workboard.
8. Request an independent fixed-scope review only when the user asks or risk warrants it.
9. Update the Room final document and emit one integrated final result. Runtime remains responsible for enforcing the unique terminal event.

## Document Responsibility

- Own the Room `BRIEF`, shared `WORKBOARD`, and `FINAL` documents.
- Let each Partner own its worker document and a Reviewer own the review document.
- Reference Runtime state rather than copying running, cancellation, workspace, or queue facts into Markdown.

## Output

Return the common `AgentResult` envelope with the integrated outcome, acceptance evidence, artifacts, document receipts, unresolved risks, and any unverified boundary.

## Not For

Do not reproduce Room rules inside task Skills, require a Kernel formatting gate, manufacture review, or treat Partner prose as automatic acceptance.

Example: a Partner implementing one bounded change uses `test-driven-implementation`; it does not load this Skill merely because its parent belongs to a Room.
