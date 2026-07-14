import { createEventBatcher } from '../../src/contracts/batching';

type StreamEvent = {
  sequence: number;
  text: string;
  pushedAt: number;
};

type QaMetrics = {
  history: {
    total: number;
    rendered: number;
    visibleAtMs: number;
    renderCostMs: number;
  };
  stream: {
    events: number;
    commits: number;
    complete: boolean;
    durationMs: number;
    p95PaintMs: number;
    longTasksOver50Ms: number;
  };
  typing: {
    samples: number;
    p95PaintMs: number;
  };
};

declare global {
  interface Window {
    __RAG_IME_QA__: {
      metrics: QaMetrics;
      startStream(): void;
    };
  }
}

const historyWindow = requiredElement<HTMLElement>('[data-testid="history-window"]');
const historyCount = requiredElement<HTMLOutputElement>('[data-testid="history-count"]');
const streamOutput = requiredElement<HTMLElement>('[data-testid="stream-output"]');
const composer = requiredElement<HTMLTextAreaElement>('[data-testid="composer"]');
const typingPaint = requiredElement<HTMLOutputElement>('[data-testid="typing-paint"]');
const connectionStatus = requiredElement<HTMLOutputElement>('[data-testid="connection-status"]');

const metrics: QaMetrics = {
  history: { total: 1_000, rendered: 0, visibleAtMs: 0, renderCostMs: 0 },
  stream: {
    events: 0,
    commits: 0,
    complete: false,
    durationMs: 0,
    p95PaintMs: 0,
    longTasksOver50Ms: 0,
  },
  typing: { samples: 0, p95PaintMs: 0 },
};

const history = Array.from({ length: metrics.history.total }, (_, index) => ({
  id: `turn-${index + 1}`,
  actor: index % 4 === 0 ? '用户' : index % 3 === 0 ? '资料鼬' : '智鼬',
  text: `消息 ${index + 1}：保留 turnId、sequence、来源和结构化活动摘要。`,
  time: `${String(Math.floor(index / 60) % 24).padStart(2, '0')}:${String(index % 60).padStart(2, '0')}`,
}));

const renderStarted = performance.now();
const visibleHistory = history.slice(-48);
const historyFragment = document.createDocumentFragment();
for (const message of visibleHistory) {
  const article = document.createElement('article');
  article.className = 'qa-turn';
  article.dataset.turn = message.id;

  const actor = document.createElement('strong');
  actor.textContent = message.actor;
  const copy = document.createElement('p');
  copy.textContent = message.text;
  const time = document.createElement('time');
  time.textContent = message.time;

  article.append(actor, copy, time);
  historyFragment.append(article);
}
historyWindow.append(historyFragment);
metrics.history.rendered = historyWindow.querySelectorAll('[data-turn]').length;
metrics.history.renderCostMs = performance.now() - renderStarted;
metrics.history.visibleAtMs = performance.now();
historyCount.textContent = `${metrics.history.rendered} / ${metrics.history.total}`;

renderTools();
renderApprovals();
renderRoom();
renderSubagents();

const typingPaintSamples: number[] = [];
composer.addEventListener('input', () => {
  const started = performance.now();
  requestAnimationFrame(() => {
    typingPaint.textContent = `${composer.value.length} chars`;
    typingPaintSamples.push(performance.now() - started);
    metrics.typing.samples = typingPaintSamples.length;
    metrics.typing.p95PaintMs = percentile(typingPaintSamples, 0.95);
  });
});

let running = false;
let streamText = '';
let streamPaintSamples: number[] = [];
let streamStarted = 0;
let longTasks: number[] = [];

const longTaskObserver = typeof PerformanceObserver === 'function' &&
  PerformanceObserver.supportedEntryTypes.includes('longtask')
  ? new PerformanceObserver((list) => {
      if (!running) return;
      longTasks.push(...list.getEntries().map((entry) => entry.duration));
    })
  : null;
longTaskObserver?.observe({ entryTypes: ['longtask'] });

const batcher = createEventBatcher<StreamEvent>({
  intervalMs: 20,
  isDelta: () => true,
  commit(events) {
    const paintedAt = performance.now();
    metrics.stream.commits += 1;
    streamText += events.map((event) => event.text).join('');
    streamPaintSamples.push(...events.map((event) => paintedAt - event.pushedAt));
    streamOutput.textContent = streamText;
  },
});

function startStream(): void {
  if (running) return;
  running = true;
  batcher.clear();
  streamText = '';
  streamPaintSamples = [];
  longTasks = [];
  metrics.stream = {
    events: 0,
    commits: 0,
    complete: false,
    durationMs: 0,
    p95PaintMs: 0,
    longTasksOver50Ms: 0,
  };
  streamStarted = performance.now();
  streamOutput.textContent = '';

  const timer = window.setInterval(() => {
    const sequence = metrics.stream.events + 1;
    batcher.push({ sequence, text: `Δ${sequence} `, pushedAt: performance.now() });
    metrics.stream.events = sequence;
    if (sequence < 200) return;

    window.clearInterval(timer);
    batcher.flush();
    metrics.stream.durationMs = performance.now() - streamStarted;
    metrics.stream.p95PaintMs = percentile(streamPaintSamples, 0.95);
    metrics.stream.longTasksOver50Ms = longTasks.filter((duration) => duration > 50).length;
    metrics.stream.complete = true;
    running = false;
  }, 5);
}

requiredElement<HTMLButtonElement>('[data-testid="start-stream"]').addEventListener('click', startStream);

requiredElement<HTMLButtonElement>('[data-testid="toggle-connection"]').addEventListener('click', () => {
  connectionStatus.dataset.state = 'offline';
  connectionStatus.textContent = 'offline';
  window.setTimeout(() => {
    connectionStatus.dataset.state = 'reconnecting';
    connectionStatus.textContent = 'reconnecting';
  }, 80);
  window.setTimeout(() => {
    connectionStatus.dataset.state = 'online';
    connectionStatus.textContent = 'online';
  }, 220);
});

window.__RAG_IME_QA__ = { metrics, startStream };

function renderTools(): void {
  const toolList = requiredElement<HTMLElement>('[data-testid="tool-list"]');
  const fragment = document.createDocumentFragment();
  for (let index = 1; index <= 8; index += 1) {
    const details = document.createElement('details');
    details.dataset.toolCall = `tool-${index}`;
    const summary = document.createElement('summary');
    summary.textContent = `工具 ${index} · ${index === 6 ? 'failed' : 'done'}`;
    const detail = document.createElement('p');
    detail.textContent = index === 6
      ? '稳定错误摘要；原始 payload 不进入主时间线。'
      : '回执、来源与耗时可展开查看。';
    details.append(summary, detail);
    fragment.append(details);
  }
  toolList.append(fragment);
}

function renderApprovals(): void {
  const approvalList = requiredElement<HTMLElement>('[data-testid="approval-list"]');
  const fragment = document.createDocumentFragment();
  for (let index = 1; index <= 4; index += 1) {
    const row = document.createElement('div');
    row.className = 'qa-approval';
    row.dataset.approval = `approval-${index}`;
    const status = document.createElement('span');
    status.textContent = index === 4 ? '已完成 · receipt-4' : `等待审批 ${index}`;
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = index === 4 ? '查看' : '批准';
    button.addEventListener('click', () => {
      status.textContent = `已完成 · receipt-${index}`;
      button.textContent = '查看';
    });
    row.append(status, button);
    fragment.append(row);
  }
  approvalList.append(fragment);
}

function renderRoom(): void {
  const room = requiredElement<HTMLElement>('[data-testid="room-participants"]');
  const participants = [
    ['智鼬', 'moderator'],
    ['资料鼬', 'research'],
    ['排错鼬', 'runtime'],
  ];
  for (const [name, role] of participants) {
    const item = document.createElement('li');
    const status = document.createElement('i');
    status.setAttribute('aria-label', '在线');
    const label = document.createElement('span');
    label.textContent = name;
    const roleLabel = document.createElement('span');
    roleLabel.textContent = role;
    item.append(status, label, roleLabel);
    room.append(item);
  }
}

function renderSubagents(): void {
  const list = requiredElement<HTMLElement>('[data-testid="subagent-list"]');
  for (let index = 1; index <= 4; index += 1) {
    const item = document.createElement('li');
    const task = document.createElement('span');
    task.textContent = `分支任务 ${index}`;
    const status = document.createElement('span');
    status.textContent = index === 4 ? 'queued' : 'done';
    item.append(task, status);
    list.append(item);
  }
}

function requiredElement<ElementType extends Element>(selector: string): ElementType {
  const element = document.querySelector<ElementType>(selector);
  if (!element) throw new Error(`Missing QA fixture element: ${selector}`);
  return element;
}

function percentile(values: readonly number[], ratio: number): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((left, right) => left - right);
  return sorted[Math.min(sorted.length - 1, Math.ceil(sorted.length * ratio) - 1)] ?? 0;
}

export {};
