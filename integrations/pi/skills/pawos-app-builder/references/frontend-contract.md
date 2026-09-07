# Extension App Frontend Contract

Read this before creating or changing an Extension App screen. The deliverable
is App-owned frontend code, not a manifest card that sends the user to Agent.

## Ownership Map

| Owner | Owns | Must not own |
| --- | --- | --- |
| Extension App | modes, domain inputs, App navigation, data-source labels, first-turn contract, result formatting, empty/error/recovery presentation | Pi loop, transcript authority, generic approval or Tool semantics |
| Generic PAWOS host | discovery, lazy mounting, icon/window identity, shared React primitives, lifecycle projection | branches for a vertical App id or business styling |
| Ordinary Pi Session | ordered transcript, Tool/thinking status, Markdown, follow-up, Steer, Stop, compaction, recovery, terminal state | App information architecture or mode meaning |
| Runtime/install inventory | installed/enabled version, App ownership, active Package/Skill binding, lifecycle receipts | browser-local claims of installation |

The App creates and restores Sessions with `surfaceKind: extension_app`, exact
`ownerAppId: manifest.id`, and a stable App-defined `surfaceKey`. App-owned
Sessions are absent from Agent's ordinary list and restored only through the
owning App. Reuse the typed control transport and embedded shared Session
workspace; do not call a Provider directly or create a second event stream.

## Implement The Frontend In This Order

1. Define a small typed mode table in the owner App. Each mode has a stable key,
   label, purpose, input contract, placeholder, and result treatment. Select a
   mode before creating a Session and bind its key as `surfaceKey`.
2. Restore only Sessions matching both the manifest owner id and known mode
   key. Keep one explicit active Session per mode unless the App contract says
   otherwise; never infer ownership from title or local storage.
3. Create/update the ordinary Session through the shared transport, enable the
   packaged App Skill through normal Session capabilities, and send the
   mode-specific first-turn contract through `agent.session.prompt`.
4. Render the live conversation with shared transcript/Composer/Tool/thinking
   primitives. App chrome may frame it, but must not reimplement ordering,
   Markdown, Stop, Steer, approvals, compaction, or terminal state.
5. Project Runtime failures as actionable UI. Preserve the draft and pending
   logical message on ambiguous send failure; do not clear the Composer until
   the Runtime accepts the message.

Build intermediate feedback into the App contract and its first foreground
check. Show actual retrieved sources and expandable excerpts when the owning
Tool returns them, before the final answer. Keep that evidence visible while
the shared Session workspace projects thinking, Tool activity and streamed
output. A spinner followed by the final result is insufficient for a multi-step
job. Do not invent stages, percentages or private reasoning to fill a delay.
Mark partial output as unfinished; preserve input/evidence on errors and use
the ordinary Session's recovery and Stop controls. Test a slow operation,
failure and restoration as well as success. For portable Lab HTML exports,
use agent-lab-project's portable App template and public progress bridge;
this native Extension App starter continues to use the shared Session surface.

For a new App, copy `assets/frontend-template/` into the new owner directory and
adapt mode names, domain copy, first-turn contract, styles, and tests. The
starter demonstrates the owner fields, embedded Session surface, and stable
message identity. It is not permission to overwrite a current App or keep its
generic sample vocabulary in the finished product.

## Stable Message And Retry Identity

Allocate one `clientMessageId` when the user commits one logical message. Store
it with the frozen message text, attachments, delivery, Session id, owner App
id, and mode key before sending. Then distinguish three Runtime outcomes:

| Evidence after the attempt | Safe next request |
| --- | --- |
| Transport timeout/disconnect or otherwise unknown admission | Replay the exact request: same `clientMessageId` and byte-equivalent semantic payload, with no `retryOfClientMessageId`. Reconcile the snapshot first when Runtime reports pending/unresolved. |
| Command receipt is durably `failed` before acceptance | Create a new `clientMessageId`, preserve the semantic payload, and set `retryOfClientMessageId` to the failed command id. Allow at most one successor for that failed receipt. |
| Command was accepted, then the turn/Provider/Tool failed | A retry is a new execution: create a new `clientMessageId` and do not send `retryOfClientMessageId`. The predecessor command was accepted, so Runtime rejects failed-command lineage. |

Never generate a UUID inside an ambiguous replay. Editing text, attachments,
delivery, or mode creates a new logical command and cannot reuse an old id.
Clear pending identity only after authoritative acceptance or explicit discard.
Deduplicate optimistic UI and restored history by identity; do not show a
second user bubble for an acknowledged replay.

## Modes, Steer, And Stop

- Switching tabs changes the visible App mode and its bound Session; it does not
  rewrite an in-flight Session's earlier contract. Preserve each mode's draft,
  pending identity, Session, and last Runtime state independently.
- Follow-up uses the ordinary Session Composer. When a turn is live, Steer uses
  Pi's native delivery path and maintains public message-before-queued ordering.
  Do not fake Steer by starting a second Session or editing the transcript.
- Stop is always visible while work is stoppable, immediately projects the
  shared `stopping` state, and waits for a real terminal/cancel escalation. Mode
  switching, closing a window, disabling an App, and uninstalling must not
  relabel a live turn as completed.
- Trace/Eval links carry explicit Session/turn/run references. They may inspect
  an App-owned Session but do not move it into Agent's ordinary history.

## Responsive And Accessible Behavior

- Test the App inside the real resizable PAWOS window, including narrow and
  short sizes. Controls may reflow, but text, Composer, errors, receipts, and
  Stop remain readable and reachable without clipped fixed-width panels.
- Mode controls use keyboard-operable tabs or an equally clear native control
  with visible focus and selected state. Every icon-only action has a name;
  status/error changes use suitable live semantics without announcing streaming
  tokens continuously.
- Keep source order useful, headings hierarchical, labels associated, contrast
  sufficient, targets usable, and reduced-motion respected. Do not encode
  mode, failure, sandbox, or installed state by color alone.
- Loading, empty, offline, retrying, stopping, failed, disabled, uninstalled,
  and version-mismatch states remain distinct. Never show connected/installed
  from a hard-coded label or the existence of checked-in source.
