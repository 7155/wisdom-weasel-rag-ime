# RAG IME UX Design v0

## Design Claim

The hard part of a RAG input method is not only retrieving the right material. The harder product problem is turning retrieved material into something a user can judge, select, and insert while typing.

Therefore:

```text
RetrievedMemory is not InputSuggestion.
RAG chunk is not input-method candidate.
```

The input-method adapter owns a `SuggestionCompiler` layer:

```text
shared RAG/memory core
  -> RetrievedMemory[]
  -> SuggestionCompiler
  -> InputSuggestion[]
  -> candidate bar / evidence preview / writing panel
```

The shared core owns persistence, FTS/vector retrieval, ranking, and memory governance. The input-method adapter owns candidateization and interaction.

## Three-Layer Display

### 1. Candidate Bar

Default UI must remain lightweight:

```text
1 高频实时场景里的个人记忆系统
2 默认本地完成, 不上传个人输入历史
3 用户选择候选会反向校准记忆源
```

Rules:

- show short phrases or one-sentence candidates;
- keep long evidence out of the candidate bar;
- keep top candidates small, normally 3 to 5 items;
- preserve normal input-method number-key selection;
- do not require the user to understand RAG before typing.

### 2. Evidence Preview

When the user focuses a RAG candidate or requests details, show a compact card:

```text
candidate: 高频实时场景里的个人记忆系统
type: phrase
confidence: 0.91
preview: RAG 输入法不是普通文档问答, 而是在输入过程中用用户选择来校准记忆源。
actions: commit / expand / pin / downrank / delete
```

Rules:

- preview must explain why the candidate appeared;
- source reference and reason are available but not forced into the candidate bar;
- actions must support user governance.

### 3. Writing Panel

Paragraph-level or multi-source output belongs in an expanded panel, not the normal candidate list.

The writing panel can support:

- insert full paragraph;
- insert first sentence;
- insert sentence by sentence;
- show source material;
- pin/downrank/delete source;
- later local model rewrite, only after explicit user action.

This panel is not the first MVP UI surface. The CLI/terminal renderer is the current acceptance surface, and a macOS overlay/WebView can come later.

## Suggestion Types

Current adapter-supported types:

```text
phrase
sentence
structure
style_hint
evidence_preview
```

Planned types:

```text
paragraph
quote
rewrite
continue
template
```

Each compiled suggestion should carry:

```text
surface_text     short candidate-bar text
insert_text      actual committed text
preview_text     expanded preview text
sources          source references
confidence       bounded score
reason           ranking or compiler reason
actions          commit / expand / pin / downrank / delete
```

## Trigger Policy

Background retrieval can update while typing, but visible RAG suggestions should not appear on every keystroke.

Accepted triggers:

- explicit user request;
- idle for at least 300 ms and current input has at least 4 characters;
- input ends at punctuation or newline;
- long-text app mode with enough input signal.

Privacy blockers:

- recording disabled;
- sensitive field;
- password/banking/private-browser app kind.

The default policy is conservative: when signal is weak or privacy is uncertain, do not show RAG suggestions.

## Local-First Constraints

- No personal input history is uploaded by default.
- GPT/Claude are not default prediction providers.
- Fine-tuning is out of scope for the Mac MVP.
- Local FTS/BM25 retrieval should return quickly.
- Local embedding/reranker/small LLM are optional later stages.
- Paragraph generation can be slower, but only after explicit user action.

## Frontend Route

Current route:

```text
Python CLI adapter MVP
  -> shared core JSON/import API
  -> terminal candidate/evidence prototype
```

Next macOS route:

```text
InputMethodKit or companion overlay
  -> local daemon / JSON command
  -> shared RAG/memory core
  -> candidate bar + evidence preview
```

Wisdom-Weasel remains an important Windows reference frontend, but the Mac MVP should not wait for Windows TSF integration.
