---
name: pawos-system
description: Explain, inspect, use, or intentionally change Personal Agent Workbench and PAWOS. Use when the user asks what PAW/PAWOS is, how its Apps, Sessions, Rooms, Browser, memory, knowledge, input, packages, themes, or windows work, or asks in natural language to customize the system across App and product boundaries. Do not use for ordinary work inside one App, a known one-file feature edit, third-party software setup, or to bypass installation, permission, confirmation, receipt, and foreground-acceptance boundaries.
metadata:
  routing:
    when:
      - 询问 PAW/PAWOS 用法
      - 跨 App、窗口或主题改造
    does: 读取最小上下文并路由现有 owner。
    input: 目标、工作区、期望结果。
    output: 说明或变更、验证与边界。
    notFor:
      - 单 App 操作
      - 绕过权限、安装或前台验收
---

# Understand And Shape PAWOS

Help a user understand or reshape Personal Agent Workbench without inventing a
second product model, command plane, or Runtime. The current source, typed
transports, reducers, App registry, settings, Runtime projections, installed
receipts, and foreground behavior remain authoritative.

This Skill is the product-level router. It does not own feature state or execute
an alternative Session loop. It follows Tutti's useful pattern of combining
host context, dynamic capability discovery, and specialized workflows while
keeping PAW's existing owners.

## Route First

Classify the current request before reading broad project context or editing:

1. **Explain:** the user asks what PAWOS is, what an App or concept does, or how
   to use it. Read only the smallest current sources needed to answer. Prefer
   live Runtime/App projections for current availability and source documents
   for durable intent. Distinguish implemented, installed, running, and
   foreground-accepted states.
2. **Operate:** the user asks to open, inspect, or use an existing App or
   capability. Discover the current Tool/App surface and invoke the owning
   action. Do not edit source when a real product action already exists.
3. **Customize:** the user asks to change an App, theme, window, workflow, or
   cross-system behavior. Bind the request to the current PAW checkout, record
   material chat-only requirements in its owned work document, inspect the
   nearest owner and consumers, then make the smallest coherent source change.
4. **Maintain:** build, install, update, uninstall, repair, rollback, LaunchAgent,
   or managed Pi Runtime work belongs to `project-maintainer`.
5. **Extend:** a missing reusable external Tool, Skill, prompt, theme, hook, or
   package belongs to `plugin-creator`; search before creating a duplicate.
6. **Decide:** if an unresolved user-owned choice changes scope, compatibility,
   cost, authority, or observable behavior, use `alignment-and-decision` before
   implementation.

Completion criterion: every explanation or change is traceable to a current
product source, live projection, user requirement, or authoritative receipt.

## Minimal Context Map

When the Session is bound to the PAW source checkout, use this order and stop
as soon as the request is grounded:

1. root `AGENTS.md`, then root `PROJECT.md` and the relevant active entry in
   root `OUTCOMES.md`;
2. `control-center-web/docs/pawos/PAWOS_REQUIREMENTS.md` as the canonical PAWOS
   requirement index. Follow only the relevant stable-ID volume, its correction
   links, and the exact **Continue reading / editing** target at the end when a
   requirement crosses a split boundary; do not treat one volume as the whole
   ledger;
3. only the relevant entries in root `CONTEXT.md`, `DECISIONS.md`, and
   `ARCHITECTURE.md`;
4. the current App registry, nearest feature owner, typed transport/reducer,
   tests, and Runtime projection for the requested surface;
5. installed status, health, or foreground evidence only when the request
   depends on current machine state.

Do not scan all docs, Session history, databases, generated output, or private
local state just to answer a product question. Do not treat prose as proof that
an App is installed, running, healthy, or accepted.

## Product Map

Use PAW's existing domain language consistently:

- **Pi** owns the Agent Session and Tool loop, Steer, Stop, compaction, and
  terminal state.
- **Session** is one explicit Agent conversation and its message, reasoning,
  Tool, Browser, child Agent, and lifecycle trajectory.
- **Room** composes ordinary Partner Sessions and owns visible collaboration,
  dispatch, Root ordering, cancellation fan-out, and satellite projections.
- **PAWOS** is the multi-window frontend and App composition layer. It does not
  become a second Agent Runtime.
- **Memory, Knowledge, Planning, Input, Browser, Files, Terminal, Packages, and
  Settings** keep their existing service and transport owners when presented as
  PAWOS Apps.
- **Rime/Squirrel** remains the native input authority; AI assistance does not
  replace Pinyin parsing or native candidate ordering.
- **Browser** is the PAW-owned visible Chromium profile shared by the human and
  Agent through the single ego-browser control stack.

Verify current App ids, routes, labels, enabled state, and controls from the App
registry and Runtime rather than memorizing a fixed inventory in this Skill.

## Customization Workflow

1. Restate the observable outcome, affected Apps/system layer, and acceptance
   boundary. Preserve exact corrections when the user supersedes an older
   requirement.
2. Find existing implementation before creating anything: App surface,
   transport path, reducer/service, settings owner, command, Skill, package, and
   tests. Recompose existing capability into PAWOS instead of cloning it.
3. For substantive work, update the owner-controlled WorkDocument before
   implementation with objective, scope, acceptance, plan, and exact references.
   When durable requirements belong in the split PAWOS ledger, preserve their
   existing stable IDs and source refs, update the canonical index/status links,
   and leave explicit `previous / index / next` and end-of-file continuation
   navigation; never hide a new volume behind repository search.
4. Preserve product boundaries: no second Session loop, Browser stack, package
   manager, settings database, event bus, input frontend, or duplicate feature
   reducer.
5. Keep interface copy limited to the current object, state, action, result, or
   recovery step. Architecture explanations belong in docs and this Skill.
6. Preserve unrelated dirty work. Never reset, clean, stash, or whole-tree
   overwrite. Delete a replaced path only after proving it has no consumer.
7. Verify in layers appropriate to the change: focused source checks, broader
   tests/build, installation/runtime health, and real foreground acceptance are
   separate evidence. Follow the user's requested test cadence.
8. Report exact changed owners, available behavior, verification evidence,
   installed-state boundary, rollback path when applicable, and residual risk.

## Truthful Output

For an explanation, return:

```text
what the user can do
where the capability lives
how to reach or use it now
current implemented/installed/running boundary
relevant limitation or recovery action
```

For a customization, return:

```text
accepted observable change
reused owners and any new thin projection
changed files or product settings
verification by source/build/install/foreground level
remaining work or rollback boundary
```

Do not claim a package is installed from a source directory, a build is running
from a successful typecheck, or a UI is accepted from a screenshot alone.
