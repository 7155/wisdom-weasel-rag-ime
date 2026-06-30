const state = {
  committed:
    "本节记录订单服务重构的设计决策。需要解决的主要问题是写入路径上的双写不一致，同事建议把订单服务的写入路径改成 outbox 模式。",
  query: "",
  focusLayer: "short",
  selectedShort: 0,
  selectedRag: 0,
  expanded: false,
  suggestions: [],
  lastPayload: null,
  timer: 0,
  apiOnline: true,
};

const fallbackSuggestions = [
  {
    suggestionId: "fallback-outbox",
    surfaceText: "把写入路径改成 outbox",
    insertText: "把订单服务的写入路径改成 outbox 模式，避免双写不一致。",
    suggestionType: "sentence",
    sourceEventId: 1,
    memoryId: "event:1",
    evidencePreview: "订单服务重构时，核心决策是把同步双写改为 outbox，避免数据库和消息系统状态不一致。",
    expandedEvidence:
      "本节记录订单服务重构的设计决策。需要解决的主要问题是写入路径上的双写不一致，同事建议把订单服务的写入路径改成 outbox 模式。",
    confidence: 0.91,
    actions: ["commit", "expand", "pin", "downrank", "delete"],
    metadata: { sources: ["implementation-notes.md"] },
  },
  {
    suggestionId: "fallback-rag-ime",
    surfaceText: "输入过程校准 RAG 上下文",
    insertText: "输入法让用户在打字过程中校准 RAG 上下文，而不是让 Agent 事后猜测。",
    suggestionType: "sentence",
    sourceEventId: 2,
    memoryId: "event:2",
    evidencePreview: "传统 RAG 是替用户找上下文，RAG 输入法则把召回入口前移到用户正在输入的过程。",
    expandedEvidence:
      "传统 RAG 的问题不是只有检索不准，而是用户没有在检索前把上下文校准清楚。输入法是最高频的写作入口，可以把选择行为变成召回反馈。",
    confidence: 0.86,
    actions: ["commit", "expand", "pin", "downrank", "delete"],
    metadata: { sources: ["project-brief.md"] },
  },
  {
    suggestionId: "fallback-raft",
    surfaceText: "Raft 拆成三个子问题",
    insertText: "Raft 共识可以拆成 Leader Election、Log Replication、Safety 三个子问题来理解。",
    suggestionType: "sentence",
    sourceEventId: 3,
    memoryId: "event:3",
    evidencePreview: "Raft 相比 Paxos 更容易讲清楚，因为它把共识流程拆成几个可独立解释的部分。",
    expandedEvidence:
      "Raft 把共识问题拆成 Leader Election、Log Replication、Safety 三个子问题，相比 Paxos 更易理解。",
    confidence: 0.78,
    actions: ["commit", "expand", "pin", "downrank", "delete"],
    metadata: { sources: ["raft-extended.pdf"] },
  },
];

const shortLexicon = ["是", "上面", "service", "方案", "所以", "safety", "outbox", "本地", "记忆", "上下文"];

const elements = {
  committedText: document.getElementById("committedText"),
  preeditText: document.getElementById("preeditText"),
  hiddenInput: document.getElementById("hiddenInput"),
  documentCard: document.getElementById("documentCard"),
  imeOverlay: document.getElementById("imeOverlay"),
  queryPill: document.getElementById("queryPill"),
  shortTier: document.getElementById("shortTier"),
  ragTier: document.getElementById("ragTier"),
  shortRow: document.getElementById("shortRow"),
  ragList: document.getElementById("ragList"),
  focusRule: document.getElementById("focusRule"),
  modeMeta: document.getElementById("modeMeta"),
  latencyMeta: document.getElementById("latencyMeta"),
  debugJson: document.getElementById("debugJson"),
  pipeline: document.getElementById("pipeline"),
  seedButton: document.getElementById("seedButton"),
  compactButton: document.getElementById("compactButton"),
  evidenceButton: document.getElementById("evidenceButton"),
};

function keyNumber(event) {
  if (!/^[0-9]$/.test(event.key)) return null;
  return event.key === "0" ? 9 : Number(event.key) - 1;
}

function shortCandidates(query) {
  const q = query.trim().toLowerCase();
  const ranked = shortLexicon.filter((item) => item.toLowerCase().includes(q) || q.includes(item.toLowerCase()));
  const merged = [...ranked, ...shortLexicon.filter((item) => !ranked.includes(item))];
  return merged.slice(0, 6);
}

function sourceLabel(suggestion) {
  const sources = suggestion?.metadata?.sources;
  if (Array.isArray(sources) && sources.length) return sources[0];
  if (suggestion?.memoryId) return suggestion.memoryId;
  return "local memory";
}

function render() {
  const query = state.query || "sa";
  const shortItems = shortCandidates(query);
  const ragItems = state.suggestions.length ? state.suggestions : fallbackSuggestions;

  elements.committedText.textContent = state.committed;
  elements.preeditText.textContent = state.query;
  elements.queryPill.textContent = state.query || "输入中";
  elements.imeOverlay.classList.toggle("is-expanded", state.expanded || state.focusLayer === "rag");
  elements.shortTier.classList.toggle("is-active", state.focusLayer === "short");
  elements.ragTier.classList.toggle("is-active", state.focusLayer === "rag");
  elements.modeMeta.textContent = state.focusLayer === "short" ? "focus short" : "focus rag";
  elements.focusRule.textContent =
    state.focusLayer === "short" ? "Tab 接受短候选 · ↓ 切 RAG · ⌥1-⌥0 直选记忆" : "1-0 选记忆 · ↑ 回短候选 · Esc 收起";

  elements.shortRow.replaceChildren(
    ...shortItems.map((item, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `short-candidate${state.focusLayer === "short" && index === state.selectedShort ? " is-selected" : ""}`;
      button.innerHTML = `<span class="num">${index + 1}</span><span>${escapeHtml(item)}</span>`;
      button.addEventListener("click", () => acceptShort(index));
      return button;
    }),
  );

  elements.ragList.replaceChildren(
    ...ragItems.slice(0, state.expanded || state.focusLayer === "rag" ? 3 : 2).map((item, index) => {
      const card = document.createElement("button");
      card.type = "button";
      card.className = `rag-card${state.focusLayer === "rag" && index === state.selectedRag ? " is-selected" : ""}`;
      card.innerHTML = `
        <span class="num">${index + 1}</span>
        <span class="rag-main">
          <span class="rag-title">${escapeHtml(item.surfaceText)}</span>
          <span class="rag-evidence">${escapeHtml(item.evidencePreview || item.expandedEvidence || "")}</span>
        </span>
        <span class="rag-source">${escapeHtml(sourceLabel(item))}</span>
      `;
      card.addEventListener("click", () => acceptRag(index));
      return card;
    }),
  );

  elements.debugJson.textContent = JSON.stringify(
    {
      query: state.query,
      focusLayer: state.focusLayer,
      expanded: state.expanded,
      apiOnline: state.apiOnline,
      suggestions: ragItems.slice(0, 3).map((item) => ({
        surfaceText: item.surfaceText,
        memoryId: item.memoryId,
        confidence: item.confidence,
      })),
    },
    null,
    2,
  );
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function suggestNow() {
  const query = state.query.trim();
  if (!query) {
    state.suggestions = fallbackSuggestions;
    render();
    return;
  }
  setPipeline("capture");
  const started = performance.now();
  try {
    setPipeline("embed");
    const response = await fetch("/api/suggest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        currentInput: query,
        recentContext: state.committed.slice(-220),
        project: "wisdom-weasel-rag-ime",
        topK: 5,
      }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    setPipeline("rank");
    const payload = await response.json();
    setPipeline("compile");
    state.lastPayload = payload;
    state.suggestions = payload.suggestions?.length ? payload.suggestions : fallbackSuggestions;
    state.apiOnline = true;
    elements.latencyMeta.textContent = `${Math.round(performance.now() - started)}ms`;
  } catch (error) {
    state.apiOnline = false;
    state.suggestions = fallbackSuggestions;
    elements.latencyMeta.textContent = "mock";
  } finally {
    window.setTimeout(() => setPipeline(""), 180);
    render();
  }
}

function debounceSuggest() {
  window.clearTimeout(state.timer);
  state.timer = window.setTimeout(suggestNow, 180);
}

function setPipeline(active) {
  for (const item of elements.pipeline.querySelectorAll("li")) {
    item.classList.toggle("is-active", item.dataset.step === active);
  }
}

function acceptShort(index) {
  const item = shortCandidates(state.query || "sa")[index];
  if (!item) return;
  const insertText = `${state.query}${item}`;
  state.committed += insertText;
  state.query = "";
  elements.hiddenInput.value = "";
  state.focusLayer = "short";
  sendCommit(insertText);
  render();
}

function acceptRag(index) {
  const item = (state.suggestions.length ? state.suggestions : fallbackSuggestions)[index];
  if (!item) return;
  const insertText = item.insertText || item.surfaceText;
  state.committed += insertText.endsWith("。") ? insertText : `${insertText}。`;
  state.query = "";
  elements.hiddenInput.value = "";
  state.focusLayer = "short";
  sendAction("accepted", item);
  sendCommit(insertText, item);
  render();
}

async function sendAction(actionType, suggestion) {
  try {
    await fetch("/api/action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        actionType,
        memoryId: suggestion.memoryId,
        suggestionId: suggestion.suggestionId,
        sourceEventId: suggestion.sourceEventId,
        query: state.query,
        surfaceText: suggestion.surfaceText,
      }),
    });
  } catch (_) {
    state.apiOnline = false;
  }
}

async function sendCommit(text, suggestion = null) {
  if (!text.trim()) return;
  try {
    await fetch("/api/commit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text,
        recentContext: state.committed.slice(-220),
        preedit: state.query,
        candidateRank: suggestion ? state.selectedRag + 1 : state.selectedShort + 1,
        providerName: suggestion ? "debug-rag" : "debug-short",
        tags: ["debug"],
      }),
    });
  } catch (_) {
    state.apiOnline = false;
  }
}

function handleKeydown(event) {
  if (event.key === "Tab") {
    event.preventDefault();
    state.focusLayer === "rag" ? acceptRag(state.selectedRag) : acceptShort(state.selectedShort);
    return;
  }
  if (event.key === "ArrowDown") {
    event.preventDefault();
    state.focusLayer = "rag";
    state.expanded = true;
    render();
    return;
  }
  if (event.key === "ArrowUp") {
    event.preventDefault();
    state.focusLayer = "short";
    state.expanded = false;
    render();
    return;
  }
  if (event.key === "Escape") {
    event.preventDefault();
    if (state.focusLayer === "rag" || state.expanded) {
      state.focusLayer = "short";
      state.expanded = false;
    } else {
      state.query = "";
      elements.hiddenInput.value = "";
    }
    render();
    return;
  }

  const numberIndex = keyNumber(event);
  if (numberIndex !== null) {
    event.preventDefault();
    if (event.altKey) {
      acceptRag(numberIndex);
    } else if (state.focusLayer === "rag") {
      acceptRag(numberIndex);
    } else {
      acceptShort(numberIndex);
    }
    return;
  }
}

function handleInput(event) {
  state.query = event.target.value;
  state.selectedShort = 0;
  state.selectedRag = 0;
  debounceSuggest();
  render();
}

async function seedDemo() {
  try {
    const response = await fetch("/api/seed", { method: "POST" });
    const payload = await response.json();
    state.lastPayload = payload;
    state.apiOnline = true;
  } catch (_) {
    state.apiOnline = false;
  }
  suggestNow();
}

elements.documentCard.addEventListener("click", () => elements.hiddenInput.focus());
elements.hiddenInput.addEventListener("keydown", handleKeydown);
elements.hiddenInput.addEventListener("input", handleInput);
elements.seedButton.addEventListener("click", seedDemo);
elements.compactButton.addEventListener("click", () => {
  state.expanded = false;
  state.focusLayer = "short";
  render();
  elements.hiddenInput.focus();
});
elements.evidenceButton.addEventListener("click", () => {
  state.expanded = !state.expanded;
  state.focusLayer = state.expanded ? "rag" : "short";
  render();
  elements.hiddenInput.focus();
});

render();
suggestNow();
