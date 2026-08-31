# Domain Context

This glossary defines the shared language used by Project, Session, Room, Skill,
and UI work. Definitions describe meaning and ownership only; implementation
details belong in architecture and source.

## Project

The durable product space that owns the original vision, current destination,
Outcomes, cross-outcome decisions, and Project documents.

_Avoid:_ using Project as a synonym for one repository checkout, Room, or live
Session.

## Original Vision

The preserved user source explaining why the Project exists. It may receive
linked clarification but is not silently rewritten by an Agent.

## Current Destination

The accepted, versionable description of the state the Project is currently
trying to reach. It is narrower and more changeable than the Original Vision.

## Outcome

A durable, independently observable user result that may be advanced by several
Sessions or Room runs.

_Avoid:_ treating Outcome as a live task, frontend card, or filesystem folder.

## Session

A private, resumable Pi conversation and execution unit with its own transcript,
context, model/Tool loop, Steer, Stop, compaction, and recovery.

## App-owned Session

A Session whose user-facing conversation belongs to one installed Extension
App. Pi still owns its transcript and execution; the App owns its visible entry
and presentation, so it is not an ordinary conversation in the Agent surface.

_Avoid:_ building a second App-specific Agent runtime, or exposing an App-owned
conversation as though the user started it in Agent.

## Room

A visible collaboration that composes a Facilitator Session and optional
Partner Sessions around one user-facing result and one final response.

_Avoid:_ Outcome Room, Room Agent Runtime, or Room as a second Session engine.

## Facilitator

The Room participant responsible for shared alignment, useful delegation,
dependency handling, integration, optional review, and the single final result.

## Partner

A visible Room participant Session with a bounded, independently accountable
responsibility. Its private transcript remains separate from public Room events.

## Tool Agent

A private child Session created by a parent Session for bounded supporting work.
Its result is evidence for the parent, not an independently accepted Project or
Room result.

_Avoid:_ subagent when it is unclear whether the participant is a visible
Partner or a private Tool Agent.

## Runtime Run

One actual execution of a Session or Room collaboration. A run produces events,
results, evidence, and artifacts but does not own Project vision.

## TaskBrief

The bounded assignment passed to a Session, Partner, or Tool Agent: objective,
scope, expected output, acceptance, references, capabilities, workspace, and
result shape.

## Work Item

A bounded responsibility with an expected result and accountable owner. It may
be projected in a Room or workboard, but its live state comes from Runtime.

## Workspace Binding

The machine-owned association between a repository/workspace, run, owner,
responsibility, access mode, and current revision or dirty state. A document may
reference the binding but does not authoritatively recreate it.

## ContextRef

An exact reference to project meaning, source, evidence, or a bounded document
body that the receiving Agent may load when needed.

## SkillRef

An exact reference to a selected method Skill and, when necessary, the subset
of its requirements that applies to the task.

## Skill

A progressively disclosed, reusable method describing when and how an Agent
should approach a class of work. It neither grants permission nor owns Runtime
state.

## Model Card

Versioned guidance about a model's operating characteristics, useful defaults,
failure tendencies, and supported controls. It is not a Persona or authority
grant.

## Persona

Versioned identity, tone, and interaction style. It must not silently alter
capabilities, workspace access, approval policy, or task ownership.

## AgentResult

A bounded return envelope containing status, result summary, decisions/defaults,
artifact or changed-file refs, verification evidence, residual risk, and next
action.

## Work Document

Agent-authored semantic material for a current brief, workboard, worker result,
review, or final explanation. It is updated by its active owner and later
organized from receipts.

## Runtime Projection

A read model derived from authoritative events and stores for current identity,
sequence, ownership, running/terminal state, Tools, cancellation, workspace, and
usage.

_Avoid:_ inferring Runtime facts from prose or Markdown checkboxes.

## Evidence

An inspectable observation, receipt, source reference, test result, or foreground
effect that supports a claim and states its scope and freshness.

## Artifact

A concrete output of work, such as a source change, patch, test, report, build,
or exported file. An artifact is not automatically accepted evidence.

## Project Field

A bounded navigation and visualization projection that combines Project
semantics with current Runtime facts. It helps the user find the right focus but
does not own or mutate either source.

## Background Organizer

A low-frequency Agent that links, checks, indexes, and condenses accepted work
documents. It does not execute product work, rewrite active meaning, or decide
completion.
