import { createRoot } from 'react-dom/client';
import { TooltipProvider } from '../../src/components/primitives';
import type { UiAgentBlock } from '../../src/contracts/ui-events';
import { AgentBlocks } from '../../src/features/agent/timeline/BlockRenderer';
import '../../src/design/tokens.css';
import '../../src/design/typography.css';
import '../../src/components/primitives/primitives.css';
import '../../src/features/agent/agent.css';

const blocks: UiAgentBlock[] = [
  { id: 'card', type: 'card', status: 'completed', presentationKind: 'card.v1', data: { title: 'Room 重构验收', tone: 'success', bodyMarkdown: '结构化内容与文字分开持久化。[证据](https://example.com/evidence) <img src=x onerror=alert(1)>', fields: [{ label: '状态', value: '通过' }, { label: '版本', value: 'v1' }] } },
  { id: 'checklist', type: 'checklist', status: 'completed', presentationKind: 'checklist.v1', data: { title: '交付清单', items: Array.from({ length: 10 }, (_, index) => ({ id: `item-${index}`, text: `验证项 ${index + 1}`, checked: index < 8 })) } },
  { id: 'table', type: 'table', status: 'completed', presentationKind: 'table.v1', data: { title: '运行矩阵', columns: ['界面', '状态'], rows: [['Agent 历史', '可重渲染'], ['Room Post', '可重渲染']] } },
  { id: 'code', type: 'code', status: 'completed', presentationKind: 'code', data: { fileName: 'runtime.log', language: 'text', code: Array.from({ length: 40 }, (_, index) => `[${index + 1}] runtime ready`).join('\n') } },
  { id: 'artifact', type: 'artifact', status: 'completed', presentationKind: 'artifact.v1', data: { title: 'room-audit.md', summary: '受控产物回执', url: '/api/agent/artifacts/audit/content' } },
  { id: 'reference', type: 'reference', status: 'completed', presentationKind: 'reference.v1', data: { title: '原始需求', source: 'Room', excerpt: '原文永久保留', url: 'javascript:alert(1)' } },
  { id: 'status', type: 'status', status: 'completed', presentationKind: 'status.v1', data: { title: 'Context Cleaner', state: 'completed', summary: '只展示 digest 与持久化 block' } },
  { id: 'unknown', type: 'unknown', rawType: 'future_chart', status: 'completed', presentationKind: 'future.v2', summary: '未来图表已安全保留', data: { title: '不展示任意 data' } },
];

createRoot(document.getElementById('root')!).render(
  <TooltipProvider><AgentBlocks blocks={blocks} /></TooltipProvider>,
);
