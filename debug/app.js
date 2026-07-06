const state = {
  committed:
    "本节记录订单服务重构的设计决策。需要解决的主要问题是写入路径上的双写不一致，同事建议把订单服务的写入路径改成 outbox 模式。",
  query: "",
  focusLayer: "short",
  selectedShort: 0,
  selectedRag: 0,
  expanded: false,
  suggestions: [],
  modelPredictions: [],
  historyContext: "",
  rimeSidecar: null,
  predictorTtfc: null,
  cacheProbe: null,
  predictionFirstMerge: false,
  inputSource: null,
  inputSourceChecking: false,
  inputSourceTimer: 0,
  memoryHistory: null,
  memorySelectedIds: new Set(),
  memoryBusy: false,
  memoryTimer: 0,
  memoryLastAction: null,
  managementView: "explain",
  managementResult: null,
  managementSelectedRowKey: "",
  managementBusy: false,
  managementLastAction: null,
  health: null,
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
  ttfcButton: document.getElementById("ttfcButton"),
  ttfcP50: document.getElementById("ttfcP50"),
  ttfcP95: document.getElementById("ttfcP95"),
  ttfcBudget: document.getElementById("ttfcBudget"),
  cacheButton: document.getElementById("cacheButton"),
  cacheCore: document.getElementById("cacheCore"),
  cacheRime: document.getElementById("cacheRime"),
  cacheRepeat: document.getElementById("cacheRepeat"),
  predictionFirstToggle: document.getElementById("predictionFirstToggle"),
  predictionFirstStatus: document.getElementById("predictionFirstStatus"),
  inputSourceButton: document.getElementById("inputSourceButton"),
  inputInstalled: document.getElementById("inputInstalled"),
  inputThirdParty: document.getElementById("inputThirdParty"),
  inputSelected: document.getElementById("inputSelected"),
  inputCurrent: document.getElementById("inputCurrent"),
  inputSourceHint: document.getElementById("inputSourceHint"),
  memoryActive: document.getElementById("memoryActive"),
  memoryGenerated: document.getElementById("memoryGenerated"),
  memoryHidden: document.getElementById("memoryHidden"),
  memoryQuery: document.getElementById("memoryQuery"),
  memorySourceText: document.getElementById("memorySourceText"),
  memoryRefreshButton: document.getElementById("memoryRefreshButton"),
  memoryGenerateButton: document.getElementById("memoryGenerateButton"),
  memoryOrganizeButton: document.getElementById("memoryOrganizeButton"),
  memoryList: document.getElementById("memoryList"),
  memoryHint: document.getElementById("memoryHint"),
  managementTabs: document.getElementById("managementTabs"),
  managementQuery: document.getElementById("managementQuery"),
  managementRefreshButton: document.getElementById("managementRefreshButton"),
  managementActionButton: document.getElementById("managementActionButton"),
  managementExportButton: document.getElementById("managementExportButton"),
  managementList: document.getElementById("managementList"),
  managementHint: document.getElementById("managementHint"),
};

function keyNumber(event) {
  if (!/^[0-9]$/.test(event.key)) return null;
  return event.key === "0" ? 9 : Number(event.key) - 1;
}

function shortCandidates(query) {
  if (state.modelPredictions.length) {
    return state.modelPredictions.map((item) => item.text).filter(Boolean).slice(0, 6);
  }
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

function sidecarDisplayCandidates() {
  if (!state.predictionFirstMerge || !state.rimeSidecar?.predictionFirst?.enabled) return [];
  const items = state.rimeSidecar.displayCandidates;
  return Array.isArray(items) ? items : [];
}

function sidecarShortCandidates() {
  return sidecarDisplayCandidates()
    .filter((item) => item.displayLayout !== "block" && item.sourceType !== "rag" && item.sourceType !== "memory")
    .slice(0, 6);
}

function sidecarRagCandidates() {
  return sidecarDisplayCandidates()
    .filter((item) => item.displayLayout === "block" || item.sourceType === "rag" || item.sourceType === "memory")
    .slice(0, 4);
}

function sidecarCandidateToSuggestion(item) {
  return {
    suggestionId: item.suggestionId || `${item.sourceType}:${item.sourceIndex}`,
    surfaceText: item.text,
    insertText: item.insertText || item.text,
    suggestionType: item.sourceType || "sidecar",
    sourceEventId: item.sourceEventId || 0,
    evidencePreview: item.evidencePreview || item.comment || "",
    expandedEvidence: item.evidencePreview || "",
    confidence: item.metadata?.confidence || 0,
    memoryId: item.memoryId || item.sourceType || "sidecar",
    metadata: { sources: [item.displayLane || item.sourceType || "sidecar"], sidecarCandidate: item },
  };
}

function render() {
  const query = state.query || "sa";
  const sidecarShort = sidecarShortCandidates();
  const sidecarRag = sidecarRagCandidates();
  const shortItems = sidecarShort.length ? sidecarShort.map((item) => item.text) : shortCandidates(query);
  const ragItems = sidecarRag.length
    ? sidecarRag.map(sidecarCandidateToSuggestion)
    : state.suggestions.length
      ? state.suggestions
      : fallbackSuggestions;

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
      modelPredictions: state.modelPredictions,
      historyContext: state.historyContext,
      predictionFirstMerge: state.predictionFirstMerge,
      rimeSidecar: state.rimeSidecar
        ? {
            queryBasis: state.rimeSidecar.queryBasis,
            triggerDecision: state.rimeSidecar.triggerDecision,
            cache: state.rimeSidecar.cache || null,
            predictionFirst: state.rimeSidecar.predictionFirst || null,
            displayCandidates: (state.rimeSidecar.displayCandidates || []).map((item) => ({
              label: item.label,
              selectionKey: item.selectionKey,
              selectionRank: item.selectionRank,
              text: item.text,
              displayLayout: item.displayLayout,
              displayLane: item.displayLane,
              sourceType: item.sourceType,
            })),
          }
        : null,
      rimeSuggestCache: state.health?.rimeSuggestCache || null,
      suggestionCache: state.health?.suggestionCache || null,
      vectorStats: state.health?.vectorStats || null,
      predictorTtfc: state.predictorTtfc
        ? {
            supported: state.predictorTtfc.benchmark?.supported,
            summary: state.predictorTtfc.benchmark?.summary,
            provider: state.predictorTtfc.predictor,
          }
        : null,
      cacheProbe: state.cacheProbe
        ? {
            summary: state.cacheProbe.summary,
            suggestionCache: state.cacheProbe.suggestionCache,
            rimeSuggestCache: state.cacheProbe.rimeSuggestCache,
            samples: state.cacheProbe.samples,
          }
        : null,
      memoryHistory: state.memoryHistory
        ? {
            totals: state.memoryHistory.totals,
            itemCount: state.memoryHistory.items?.length || 0,
            selected: Array.from(state.memorySelectedIds),
            lastAction: state.memoryLastAction,
          }
        : null,
      inputSource: state.inputSource
        ? {
            ok: state.inputSource.ok,
            typingReady: state.inputSource.typingReady,
            id: state.inputSource.id,
            current: state.inputSource.current,
            enabled: state.inputSource.enabled,
            selectable: state.inputSource.selectable,
            selected: state.inputSource.selected,
            hitoolboxEnabled: state.inputSource.hitoolboxEnabled,
            thirdPartyEnabled: state.inputSource.thirdPartyEnabled,
            readinessState: state.inputSource.readinessState,
            nextAction: state.inputSource.nextAction,
            manualAction: state.inputSource.manualAction,
            helperCommand: state.inputSource.helperCommand,
            verificationCommand: state.inputSource.verificationCommand,
            readinessChecks: state.inputSource.readinessChecks,
          }
        : null,
    },
    null,
    2,
  );

  renderTtfc();
  renderCacheProbe();
  renderPredictionFirst();
  renderInputSource();
  renderMemoryConsole();
  renderManagementConsole();
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
    state.modelPredictions = [];
    state.historyContext = "";
    state.suggestions = fallbackSuggestions;
    if (state.predictionFirstMerge && state.committed.trim()) {
      await refreshPostCommitPredictions("");
      return;
    }
    state.rimeSidecar = null;
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
    state.modelPredictions = Array.isArray(payload.modelPredictions) ? payload.modelPredictions : [];
    state.historyContext = payload.historyContext || "";
    state.suggestions = payload.suggestions?.length ? payload.suggestions : fallbackSuggestions;
    state.rimeSidecar = await probeRimeSidecar(query);
    state.apiOnline = true;
    elements.latencyMeta.textContent = `${Math.round(performance.now() - started)}ms`;
  } catch (error) {
    state.apiOnline = false;
    state.modelPredictions = [];
    state.historyContext = "";
    state.rimeSidecar = null;
    state.suggestions = fallbackSuggestions;
    elements.latencyMeta.textContent = "mock";
  } finally {
    window.setTimeout(() => setPipeline(""), 180);
    render();
  }
}

async function probeRimeSidecar(query, options = {}) {
  const candidates = query
    ? shortCandidates(query)
        .slice(0, 2)
        .map((item, index) => ({
          label: String(index + 1),
          text: item,
          comment: "debug-rime",
          index,
        }))
    : [];
  const response = await fetch("/api/rime-suggest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sessionId: "debug-page",
      requestSeq: Date.now(),
      rawInput: query,
      preedit: query,
      commitTextPreview: options.commitTextPreview || "",
      committedContext: state.committed.slice(-220),
      idleMs: options.idleMs ?? 0,
      maxVisibleCandidates: 6,
      maxSideCandidates: 2,
      predictionFirstMerge: state.predictionFirstMerge,
      forceSideCandidates: options.forceSideCandidates === true,
      rimeContext: {
        candidates,
        highlightedIndex: 0,
        page: 0,
        isLastPage: true,
      },
    }),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

async function refreshPostCommitPredictions(anchorText) {
  if (!state.predictionFirstMerge || !state.committed.trim()) return;
  setPipeline("rank");
  try {
    state.rimeSidecar = await probeRimeSidecar("", {
      commitTextPreview: anchorText,
      forceSideCandidates: true,
      idleMs: 120,
    });
    state.apiOnline = true;
  } catch (_) {
    state.rimeSidecar = null;
    state.apiOnline = false;
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
  const sidecarItem = sidecarShortCandidates()[index];
  if (sidecarItem) {
    acceptSidecarCandidate(sidecarItem);
    return;
  }
  const item = shortCandidates(state.query || "sa")[index];
  if (!item) return;
  const insertText = `${state.query}${item}`;
  state.committed += insertText;
  state.query = "";
  elements.hiddenInput.value = "";
  state.focusLayer = "short";
  sendCommit(insertText);
  render();
  refreshPostCommitPredictions(insertText);
}

function acceptRag(index) {
  const sidecarItem = sidecarRagCandidates()[index];
  if (sidecarItem) {
    acceptSidecarCandidate(sidecarItem);
    return;
  }
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
  refreshPostCommitPredictions(insertText);
}

async function acceptSidecarCandidate(candidate) {
  const insertText = candidate.insertText || candidate.text;
  if (!insertText) return;
  state.committed += insertText;
  state.query = "";
  elements.hiddenInput.value = "";
  state.focusLayer = "short";
  await sendRimeSelect(candidate);
  render();
  await refreshPostCommitPredictions(insertText);
}

async function sendRimeSelect(candidate) {
  try {
    await fetch("/api/rime-select", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        candidate,
        query: state.query,
        semanticQuery: state.rimeSidecar?.semanticQuery || "",
        recentContext: state.committed.slice(-220),
        committedContext: state.committed.slice(-220),
        preedit: state.query,
        project: "wisdom-weasel-rag-ime",
        source: "debug_prediction_first",
        providerName: `debug-${candidate.sourceType || "sidecar"}`,
      }),
    });
    state.apiOnline = true;
  } catch (_) {
    state.apiOnline = false;
  }
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
    await refreshHealth();
  } catch (_) {
    state.apiOnline = false;
  }
  suggestNow();
}

async function refreshHealth() {
  try {
    const response = await fetch("/api/health");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.health = await response.json();
    state.apiOnline = true;
  } catch (_) {
    state.health = null;
    state.apiOnline = false;
  }
}

async function refreshMemoryHistory() {
  state.memoryBusy = true;
  renderMemoryConsole();
  try {
    const response = await fetch("/api/memory-history", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: elements.memoryQuery.value.trim(),
        project: "wisdom-weasel-rag-ime",
        limit: 30,
      }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.memoryHistory = await response.json();
    state.apiOnline = true;
  } catch (error) {
    state.memoryHistory = { ok: false, error: String(error), items: [], totals: {} };
    state.apiOnline = false;
  } finally {
    state.memoryBusy = false;
    render();
  }
}

function renderMemoryConsole() {
  const history = state.memoryHistory || {};
  const totals = history.totals || {};
  const items = Array.isArray(history.items) ? history.items : [];
  elements.memoryActive.textContent = Number.isFinite(totals.active) ? String(totals.active) : "--";
  elements.memoryGenerated.textContent = Number.isFinite(totals.generated) ? String(totals.generated) : "--";
  elements.memoryHidden.textContent = Number.isFinite(totals.hidden) ? String(totals.hidden) : "--";
  elements.memoryRefreshButton.disabled = state.memoryBusy;
  elements.memoryGenerateButton.disabled = state.memoryBusy;
  elements.memoryOrganizeButton.disabled = state.memoryBusy;
  elements.memoryRefreshButton.textContent = state.memoryBusy ? "loading" : "refresh";
  const selectedCount = state.memorySelectedIds.size;
  const last = state.memoryLastAction;
  elements.memoryHint.textContent = [
    history.error,
    selectedCount ? `${selectedCount} selected` : `${items.length} rows`,
    last?.message,
  ]
    .filter(Boolean)
    .join(" · ");
  elements.memoryList.replaceChildren(
    ...items.slice(0, 8).map((item) => {
      const row = document.createElement("label");
      row.className = "memory-row";
      const checked = state.memorySelectedIds.has(item.eventId);
      row.innerHTML = `
        <input type="checkbox" ${checked ? "checked" : ""} />
        <span class="memory-row-main">
          <span class="memory-row-text">${escapeHtml(item.text || "")}</span>
          <span class="memory-row-meta">${escapeHtml([item.eventId, item.source, item.providerName].filter(Boolean).join(" · "))}</span>
        </span>
      `;
      row.querySelector("input").addEventListener("change", (event) => {
        if (event.target.checked) state.memorySelectedIds.add(item.eventId);
        else state.memorySelectedIds.delete(item.eventId);
        renderMemoryConsole();
      });
      return row;
    }),
  );
}

function renderManagementConsole() {
  const result = state.managementResult || {};
  const rows = managementRows(result);
  ensureManagementSelection(rows);
  for (const button of elements.managementTabs.querySelectorAll("button")) {
    button.classList.toggle("is-active", button.dataset.view === state.managementView);
  }
  elements.managementRefreshButton.disabled = state.managementBusy;
  elements.managementActionButton.disabled = state.managementBusy || !managementActionTarget(rows);
  elements.managementExportButton.disabled = state.managementBusy || state.managementView !== "lexicon";
  elements.managementActionButton.textContent = managementActionLabel(rows);
  elements.managementHint.textContent = [
    state.managementBusy ? "loading" : "",
    result.rawTextVisible === false ? "redacted" : "",
    state.managementLastAction?.message,
    result.error,
    `${rows.length} rows`,
  ]
    .filter(Boolean)
    .join(" · ");
  elements.managementList.replaceChildren(
    ...rows.slice(0, 8).map((row) => {
      const rowKey = managementRowKey(row);
      const item = document.createElement("div");
      item.className = `memory-row management-row${rowKey === state.managementSelectedRowKey ? " is-selected" : ""}`;
      item.tabIndex = 0;
      item.setAttribute("role", "button");
      item.setAttribute("aria-pressed", rowKey === state.managementSelectedRowKey ? "true" : "false");
      item.innerHTML = `
        <span class="source-chip">${escapeHtml(row.source)}</span>
        <span class="memory-row-main">
          <span class="memory-row-text">${escapeHtml(row.title)}</span>
          <span class="memory-row-meta">${escapeHtml(row.meta)}</span>
        </span>
      `;
      item.addEventListener("click", () => selectManagementRow(rowKey));
      item.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        selectManagementRow(rowKey);
      });
      return item;
    }),
  );
}

function managementRows(result) {
  if (!result || result.ok === false) return [];
  if (state.managementView === "explain") {
    return (result.candidates || []).map((item) => ({
      source: item.sourceType || "candidate",
      title: item.text || item.textPreview || item.memoryId || "",
      meta: [item.lane, item.score, item.reason].filter((part) => part !== undefined && part !== "").join(" · "),
      raw: item,
    }));
  }
  if (state.managementView === "history") {
    return (result.items || []).map((item) => ({
      source: item.source || "history",
      title: item.text || item.textPreview || item.textHash || "",
      meta: [item.eventId, item.app, item.providerName, item.deleted ? "deleted" : ""].filter(Boolean).join(" · "),
      raw: item,
    }));
  }
  if (state.managementView === "memories" || state.managementView === "lexicon") {
    return (result.items || []).map((item) => ({
      source: item.kind || state.managementView,
      title: item.text || item.textPreview || item.memoryId || "",
      meta: [item.memoryId, item.status, item.qualityScore].filter((part) => part !== undefined && part !== "").join(" · "),
      raw: item,
    }));
  }
  if (state.managementView === "cleanup") {
    const rows = [];
    for (const run of result.items || []) {
      for (const diff of run.diffs || []) {
        rows.push({
          source: diff.op || "diff",
          title: diff.targetMemoryId || diff.diffId || run.runId || "",
          meta: [diff.diffId, diff.status, run.status].filter(Boolean).join(" · "),
          raw: diff,
        });
      }
    }
    if (result.diff) {
      rows.push({
        source: result.diff.op || "diff",
        title: result.diff.targetMemoryId || result.diff.diffId || "",
        meta: [result.diff.diffId, result.diff.status].filter(Boolean).join(" · "),
        raw: result.diff,
      });
    }
    return rows;
  }
  return [];
}

function managementActionTarget(rows) {
  ensureManagementSelection(rows);
  return rows.find((row) => managementRowKey(row) === state.managementSelectedRowKey)?.raw || null;
}

function managementActionLabel(rows) {
  const target = managementActionTarget(rows);
  if (!target) return "action";
  if (state.managementView === "history") return "tombstone";
  if (state.managementView === "memories" || state.managementView === "lexicon") return "approve";
  if (state.managementView === "cleanup") return target.status === "applied" ? "rollback" : "apply";
  return "inspect";
}

function managementRowKey(row) {
  const raw = row?.raw || {};
  return [
    state.managementView,
    raw.diffId || raw.eventId || raw.memoryId || raw.candidateId || raw.textHash || raw.targetMemoryId || row.title || "",
    raw.status || raw.op || row.source || "",
  ].join(":");
}

function ensureManagementSelection(rows) {
  if (!rows.length) {
    state.managementSelectedRowKey = "";
    return;
  }
  if (!rows.some((row) => managementRowKey(row) === state.managementSelectedRowKey)) {
    state.managementSelectedRowKey = managementRowKey(rows[0]);
  }
}

function selectManagementRow(rowKey) {
  state.managementSelectedRowKey = rowKey;
  renderManagementConsole();
}

function confirmCleanupDiffAction(action, target) {
  const diffId = target.diffId || target.id || "";
  return window.confirm(`Confirm cleanup diff ${action}${diffId ? ` #${diffId}` : ""}?`);
}

async function refreshManagementConsole() {
  state.managementBusy = true;
  renderManagementConsole();
  try {
    const query = elements.managementQuery.value.trim();
    let url = "/api/candidates/explain";
    if (state.managementView === "history") url = "/api/history";
    else if (state.managementView === "memories") url = "/api/memories";
    else if (state.managementView === "lexicon") url = "/api/lexicon";
    else if (state.managementView === "cleanup") url = "/api/cleanup-diff";
    const params = new URLSearchParams({
      project: "wisdom-weasel-rag-ime",
      limit: "20",
    });
    if (query) params.set(state.managementView === "explain" ? "query" : "query", query);
    if (state.managementView === "explain" && !query) params.set("query", state.query || "RAG 输入法");
    if (state.managementView === "memories" || state.managementView === "lexicon") params.set("status", "pending");
    const response = await fetch(`${url}?${params.toString()}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.managementResult = await response.json();
    ensureManagementSelection(managementRows(state.managementResult));
    state.apiOnline = true;
  } catch (error) {
    state.managementResult = { ok: false, error: String(error) };
    state.apiOnline = false;
  } finally {
    state.managementBusy = false;
    render();
  }
}

async function runManagementAction() {
  const rows = managementRows(state.managementResult || {});
  const target = managementActionTarget(rows);
  if (!target) return;
  state.managementBusy = true;
  renderManagementConsole();
  try {
    let endpoint = "";
    let body = {};
    if (state.managementView === "history") {
      endpoint = "/api/history/tombstone";
      body = { eventId: target.eventId, reason: "debug-management" };
    } else if (state.managementView === "memories") {
      endpoint = "/api/memories/action";
      body = { memoryId: target.memoryId, action: "approve" };
    } else if (state.managementView === "lexicon") {
      endpoint = "/api/lexicon/action";
      body = { memoryId: target.memoryId, action: "approve" };
    } else if (state.managementView === "cleanup") {
      const action = target.status === "applied" ? "rollback" : "apply";
      if (!confirmCleanupDiffAction(action, target)) {
        state.managementLastAction = { message: `${action} cancelled` };
        return;
      }
      endpoint = action === "rollback" ? "/api/cleanup-diff/rollback" : "/api/cleanup-diff/apply";
      body = { diffId: target.diffId, confirm: action };
    } else {
      await refreshManagementConsole();
      return;
    }
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await response.json();
    if (!response.ok || payload.ok === false) throw new Error(payload.error || `HTTP ${response.status}`);
    state.managementLastAction = { message: `audit ${payload.auditId || "ok"}` };
    await refreshManagementConsole();
  } catch (error) {
    state.managementLastAction = { message: String(error) };
  } finally {
    state.managementBusy = false;
    render();
  }
}

async function exportManagementLexicon() {
  if (state.managementView !== "lexicon") return;
  state.managementBusy = true;
  renderManagementConsole();
  try {
    const response = await fetch("/api/lexicon/export-rime", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project: "wisdom-weasel-rag-ime",
        status: "approved",
        dryRun: true,
        limit: 200,
      }),
    });
    const payload = await response.json();
    if (!response.ok || payload.ok === false) throw new Error(payload.error || `HTTP ${response.status}`);
    state.managementLastAction = { message: `export preview ${payload.entryCount || 0}` };
    state.lastPayload = payload;
  } catch (error) {
    state.managementLastAction = { message: String(error) };
  } finally {
    state.managementBusy = false;
    render();
  }
}

async function generateMemoryFromConsole() {
  state.memoryBusy = true;
  renderMemoryConsole();
  try {
    const response = await fetch("/api/generate-memory", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: elements.memorySourceText.value.trim(),
        eventIds: Array.from(state.memorySelectedIds),
        recentContext: state.committed.slice(-260),
        project: "wisdom-weasel-rag-ime",
        maxItems: 3,
      }),
    });
    const payload = await response.json();
    if (!response.ok || payload.ok === false) throw new Error(payload.error || `HTTP ${response.status}`);
    state.memoryLastAction = { message: `recorded ${payload.recorded}, skipped ${payload.duplicateSkipped}` };
    state.memorySelectedIds.clear();
    await refreshMemoryHistory();
  } catch (error) {
    state.memoryLastAction = { message: String(error) };
  } finally {
    state.memoryBusy = false;
    render();
  }
}

async function organizeMemoryDryRun() {
  state.memoryBusy = true;
  renderMemoryConsole();
  try {
    const response = await fetch("/api/organize-rag-db", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project: "wisdom-weasel-rag-ime",
        dryRun: true,
        sampleSize: 5,
      }),
    });
    const payload = await response.json();
    if (!response.ok || payload.ok === false) throw new Error(payload.error || `HTTP ${response.status}`);
    state.memoryLastAction = { message: `noise ${payload.matchedNoise}, stale vectors ${payload.staleHiddenVectors}` };
  } catch (error) {
    state.memoryLastAction = { message: String(error) };
  } finally {
    state.memoryBusy = false;
    render();
  }
}

function renderTtfc() {
  const summary = state.predictorTtfc?.benchmark?.summary || {};
  const supported = state.predictorTtfc?.benchmark?.supported;
  const p50 = Number(summary.p50FirstCandidateMs || 0);
  const p95 = Number(summary.p95FirstCandidateMs || 0);
  const over = Number(summary.overBudgetCount || 0);
  elements.ttfcP50.textContent = p50 ? `${p50}ms` : "--";
  elements.ttfcP95.textContent = p95 ? `${p95}ms` : "--";
  elements.ttfcBudget.textContent = supported === false ? "off" : String(over || 0);
  elements.ttfcButton.classList.toggle("is-warn", supported === false || over > 0);
}

function renderCacheProbe() {
  const summary = state.cacheProbe?.summary || {};
  const coreHits = Number(summary.suggestionCacheHitDelta || 0);
  const rimeHits = Number(summary.rimeCacheHitDelta || 0);
  const repeat = Number(state.cacheProbe?.repeat || 0);
  const corePassed = summary.suggestionCachePassed;
  const rimePassed = summary.rimeCachePassed;
  elements.cacheCore.textContent = repeat ? String(coreHits) : "--";
  elements.cacheRime.textContent = repeat ? String(rimeHits) : "--";
  elements.cacheRepeat.textContent = repeat ? String(repeat) : "--";
  elements.cacheButton.classList.toggle("is-warn", corePassed === false || rimePassed === false);
}

function renderPredictionFirst() {
  const meta = state.rimeSidecar?.predictionFirst || {};
  const policy = meta.policy || {};
  elements.predictionFirstToggle.checked = state.predictionFirstMerge;
  elements.predictionFirstStatus.textContent = [
    meta.enabled ? meta.mode || "prediction-first" : "legacy sidecar merge",
    meta.pinyinPrefix ? `prefix=${meta.pinyinPrefix}` : "",
    Number.isFinite(policy.sideInserted) ? `side=${policy.sideInserted}` : "",
    Number.isFinite(policy.wanxiangFallbackCount) ? `wanxiang=${policy.wanxiangFallbackCount}` : "",
  ]
    .filter(Boolean)
    .join(" · ");
}

function compactInputSourceId(value) {
  const text = String(value || "");
  if (!text) return "--";
  if (text.includes("Squirrel")) return "Squirrel";
  if (text.includes("doubaoime")) return "Doubao";
  if (text.includes("SCIM")) return "Pinyin";
  if (text.includes("ABC")) return "ABC";
  return text.split(".").at(-1) || text;
}

function compactBool(value) {
  if (value === true) return "yes";
  if (value === false) return "no";
  return "--";
}

function renderInputSource() {
  const status = state.inputSource || {};
  const readiness = status.readinessState || "check";
  const nextCommand = status.helperCommand || status.verificationCommand;
  elements.inputInstalled.textContent =
    status.available === false ? "off" : compactBool(status.enabled === true && status.selectable === true);
  elements.inputThirdParty.textContent = compactBool(status.thirdPartyEnabled);
  elements.inputSelected.textContent = status.typingReady ? "yes" : status.selected === false ? "no" : "--";
  elements.inputCurrent.textContent = compactInputSourceId(status.current);
  elements.inputSourceHint.textContent = [
    status.readinessMessage || status.error || "waiting for status",
    status.nextAction,
    nextCommand,
  ]
    .filter(Boolean)
    .join(" · ");
  elements.inputSourceButton.textContent = state.inputSourceChecking ? "checking" : readiness;
  elements.inputSourceButton.disabled = state.inputSourceChecking;
  elements.inputSourceButton.classList.toggle("is-good", status.typingReady === true);
  elements.inputSourceButton.classList.toggle("is-warn", status.ok === false || status.typingReady === false);
}

async function refreshInputSource(options = {}) {
  const silent = options.silent === true;
  if (!silent) {
    state.inputSourceChecking = true;
    render();
  }
  try {
    const response = await fetch("/api/input-source");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.inputSource = await response.json();
    state.apiOnline = true;
  } catch (error) {
    state.inputSource = {
      available: false,
      ok: false,
      typingReady: false,
      error: String(error),
    };
    state.apiOnline = false;
  } finally {
    state.inputSourceChecking = false;
    render();
  }
}

function startInputSourcePolling() {
  window.clearInterval(state.inputSourceTimer);
  state.inputSourceTimer = window.setInterval(() => refreshInputSource({ silent: true }), 2500);
}

async function probePredictorTtfc() {
  elements.ttfcButton.disabled = true;
  elements.ttfcButton.textContent = "probing";
  try {
    const response = await fetch("/api/predictor-ttfc", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        currentInput: state.query || "RAG 输入法",
        recentContext: state.committed.slice(-220),
        repeat: 3,
        maxCandidates: 3,
        latencyBudgetMs: 200,
      }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.predictorTtfc = await response.json();
    state.apiOnline = true;
  } catch (error) {
    state.predictorTtfc = {
      benchmark: {
        supported: false,
        summary: {},
        error: String(error),
      },
    };
    state.apiOnline = false;
  } finally {
    elements.ttfcButton.disabled = false;
    elements.ttfcButton.textContent = "probe";
    render();
  }
}

async function probeCache() {
  elements.cacheButton.disabled = true;
  elements.cacheButton.textContent = "probing";
  try {
    const response = await fetch("/api/cache-probe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        currentInput: state.query || "RAG 输入法",
        recentContext: state.committed.slice(-220),
        repeat: 3,
        topK: 5,
      }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.cacheProbe = await response.json();
    state.apiOnline = true;
  } catch (error) {
    state.cacheProbe = {
      repeat: 0,
      summary: {
        suggestionCachePassed: false,
        rimeCachePassed: false,
        error: String(error),
      },
    };
    state.apiOnline = false;
  } finally {
    elements.cacheButton.disabled = false;
    elements.cacheButton.textContent = "probe";
    render();
  }
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
elements.ttfcButton.addEventListener("click", probePredictorTtfc);
elements.cacheButton.addEventListener("click", probeCache);
elements.memoryRefreshButton.addEventListener("click", refreshMemoryHistory);
elements.memoryGenerateButton.addEventListener("click", generateMemoryFromConsole);
elements.memoryOrganizeButton.addEventListener("click", organizeMemoryDryRun);
elements.memoryQuery.addEventListener("input", () => {
  window.clearTimeout(state.memoryTimer);
  state.memoryTimer = window.setTimeout(refreshMemoryHistory, 250);
});
elements.managementTabs.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-view]");
  if (!button) return;
  state.managementView = button.dataset.view;
  state.managementResult = null;
  state.managementSelectedRowKey = "";
  refreshManagementConsole();
});
elements.managementRefreshButton.addEventListener("click", refreshManagementConsole);
elements.managementActionButton.addEventListener("click", runManagementAction);
elements.managementExportButton.addEventListener("click", exportManagementLexicon);
elements.managementQuery.addEventListener("input", () => {
  window.clearTimeout(state.memoryTimer);
  state.memoryTimer = window.setTimeout(refreshManagementConsole, 250);
});
elements.predictionFirstToggle.addEventListener("change", () => {
  state.predictionFirstMerge = elements.predictionFirstToggle.checked;
  state.rimeSidecar = null;
  render();
  suggestNow();
  elements.hiddenInput.focus();
});
elements.inputSourceButton.addEventListener("click", refreshInputSource);

render();
refreshHealth().then(render);
refreshMemoryHistory();
refreshManagementConsole();
refreshInputSource({ silent: true });
startInputSourcePolling();
suggestNow();
