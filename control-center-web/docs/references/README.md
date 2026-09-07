# React OS references

React OS is the current PAWOS frontend in this repository. Its desktop code is
in `src/paw-os`; shared feature owners are in `src/features`. Start development
at [CLOUD_MODEL.md](../../CLOUD_MODEL.md).

The historical upstream projects [7155/tutti](https://github.com/7155/tutti)
and [tutti-os/tutti](https://github.com/tutti-os/tutti) supplied interaction
references. Their original names, URLs, licenses and quoted requirements remain
attributed to those projects. The name React OS applies to the current PAW
frontend, not to those upstream repositories. No external checkout is required.

## Supplied packages

| Archive | Product attribution |
| --- | --- |
| [conversation_ui_standalone.zip](packages/conversation_ui_standalone.zip) | [Conversation UI](../../src/features/conversation-ui/ATTRIBUTION.md) |
| [paw-agent-chat-ui-kit-source.zip](packages/paw-agent-chat-ui-kit-source.zip) | [Chat UI Kit](../../src/features/agent/timeline/chat-ui-kit/ATTRIBUTION.md) and [progressive Markdown](../../src/features/agent/timeline/progressive-markdown/ATTRIBUTION.md) |

These original MIT packages retain the LICENSE files inside their archives.
They moved here from the repository root without content changes. Runtime code
uses the attributed source modules, not ZIP imports. The other directories in
this folder retain their own provenance and license files.

[pawos-conversation-baseline.html](pawos-conversation-baseline.html) remains a
visual reference. Dated design QA is under [history](../history/); Room blackbox
records are under [eval/room-blackbox](../../../eval/room-blackbox/).
