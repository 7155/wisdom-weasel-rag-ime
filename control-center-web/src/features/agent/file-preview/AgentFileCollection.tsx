import { ChevronDown, Files, History } from 'lucide-react';
import { Disclosure } from '@/components/primitives';
import type { UiAgentBlock } from '@/contracts/ui-events';
import { AgentFileBlock } from './AgentFileBlock';
import './file-preview.css';

interface AgentFileCollectionProps {
  blocks: UiAgentBlock[];
  sessionId?: string;
}

interface LogicalFileGroup {
  name: string;
  snapshots: UiAgentBlock[];
  changes: UiAgentBlock[];
  duplicateCount: number;
}

export function AgentFileCollection({ blocks, sessionId = '' }: AgentFileCollectionProps) {
  const groups = groupFileBlocks(blocks);
  const uniqueResultCount = groups.reduce(
    (count, group) => count + group.snapshots.length + group.changes.length,
    0,
  );
  const duplicateCount = groups.reduce((count, group) => count + group.duplicateCount, 0);

  return (
    <section aria-label="结果文件" className="agent-file-collection">
      <header className="agent-file-collection__header">
        <span><Files aria-hidden="true" size={17} /><strong>结果文件</strong></span>
        <small>
          {groups.length} 个文件 · {uniqueResultCount} 条结果
          {duplicateCount > 0 ? ` · 已合并 ${duplicateCount} 条重复结果` : ''}
        </small>
      </header>
      <div className="agent-file-collection__files">
        {groups.map((group) => (
          <Disclosure className="agent-file-collection__file" key={group.name} contentClassName="agent-file-collection__history" summary={<>
              <span className="agent-file-collection__file-icon"><History aria-hidden="true" size={16} /></span>
              <span>
                <strong>{group.name}</strong>
                <small>{fileHistoryLabel(group)}</small>
              </span>
              <span aria-hidden="true" className="agent-file-collection__toggle">
                查看版本 <ChevronDown size={15} />
              </span>
            </>}>
              <FileVersionSeries
                blocks={group.snapshots}
                currentLabel="当前文件"
                historyLabel="文件版本"
                sessionId={sessionId}
              />
              <FileVersionSeries
                blocks={group.changes}
                currentLabel="最近修改"
                historyLabel="修改记录"
                sessionId={sessionId}
              />
          </Disclosure>
        ))}
      </div>
    </section>
  );
}

function FileVersionSeries({
  blocks,
  currentLabel,
  historyLabel,
  sessionId,
}: {
  blocks: UiAgentBlock[];
  currentLabel: string;
  historyLabel: string;
  sessionId: string;
}) {
  if (blocks.length === 0) return null;
  return (
    <div className="agent-file-collection__series">
      {[...blocks].reverse().map((block, index) => (
        <div
          className="agent-file-collection__version"
          data-current={index === 0 || undefined}
          key={`${block.id}:${fileReceiptIdentity(block)}`}
        >
          <small>{index === 0 ? currentLabel : `${historyLabel} ${blocks.length - index}`}</small>
          <AgentFileBlock data={block.data} sessionId={sessionId} />
        </div>
      ))}
    </div>
  );
}

function groupFileBlocks(blocks: UiAgentBlock[]): LogicalFileGroup[] {
  const groups = new Map<string, LogicalFileGroup>();
  const seenReceipts = new Set<string>();
  for (const block of blocks) {
    const fileName = blockFileName(block);
    const change = isChangeReceipt(block, fileName);
    const logicalName = change ? fileName.replace(/\.(?:diff|patch)$/iu, '') || fileName : fileName;
    const group = groups.get(logicalName) ?? {
      name: logicalName,
      snapshots: [],
      changes: [],
      duplicateCount: 0,
    };
    if (!groups.has(logicalName)) groups.set(logicalName, group);

    const identity = fileReceiptIdentity(block);
    if (seenReceipts.has(identity)) {
      group.duplicateCount += 1;
      continue;
    }
    seenReceipts.add(identity);
    (change ? group.changes : group.snapshots).push(block);
  }
  return [...groups.values()];
}

function fileHistoryLabel(group: LogicalFileGroup): string {
  const parts = [];
  if (group.snapshots.length > 0) parts.push(`${group.snapshots.length} 个文件版本`);
  if (group.changes.length > 0) parts.push(`${group.changes.length} 份修改记录`);
  if (group.duplicateCount > 0) parts.push(`合并 ${group.duplicateCount} 条重复`);
  return parts.join(' · ');
}

function isChangeReceipt(block: UiAgentBlock, fileName: string): boolean {
  return /\.(?:diff|patch)$/iu.test(fileName)
    || /(?:diff|patch)/iu.test(text(block.data.mimeType));
}

function blockFileName(block: UiAgentBlock): string {
  return text(block.data.fileName ?? block.data.name ?? block.data.title) || '文件产物';
}

function fileReceiptIdentity(block: UiAgentBlock): string {
  const fileName = blockFileName(block);
  const receipt = text(block.data.sha256)
    || text(block.data.mediaId)
    || text(block.data.receiptUrl)
    || text(block.digest)
    || block.id;
  return `${fileName}\u0000${receipt}`;
}

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}
