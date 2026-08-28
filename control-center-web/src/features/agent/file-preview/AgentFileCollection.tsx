import type { UiAgentBlock } from '@/contracts/ui-events';
import { AgentFileBlock } from './AgentFileBlock';
import './file-preview.css';

interface AgentFileCollectionProps {
  blocks: UiAgentBlock[];
  sessionId?: string;
}

interface LogicalFileGroup {
  name: string;
  latest: UiAgentBlock;
}

export function AgentFileCollection({ blocks, sessionId = '' }: AgentFileCollectionProps) {
  const groups = groupFileBlocks(blocks);

  return (
    <section aria-label="结果文件" className="agent-file-collection">
      {groups.map((group) => (
        <AgentFileBlock
          data={group.latest.data}
          key={`${group.name}:${fileReceiptIdentity(group.latest)}`}
          sessionId={sessionId}
        />
      ))}
    </section>
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
      latest: block,
    };
    if (!groups.has(logicalName)) groups.set(logicalName, group);

    const identity = fileReceiptIdentity(block);
    if (seenReceipts.has(identity)) {
      continue;
    }
    seenReceipts.add(identity);
    // The transcript still carries every receipt, but the message surface only
    // needs one authoritative, latest file block. This removes the old
    // collection -> version -> block -> preview card stack while preserving
    // Markdown/diff preview behavior through AgentFileBlock.
    group.latest = block;
  }
  return [...groups.values()];
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
