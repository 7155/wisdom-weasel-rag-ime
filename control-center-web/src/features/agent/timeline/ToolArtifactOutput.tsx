import type { UiAgentBlock } from '@/contracts/ui-events';
import { AgentFileBlock } from '../file-preview/AgentFileBlock';
import { DiffPreview } from '../file-preview/DiffPreview';

export function ToolArtifactOutput({
  artifacts,
  autoExpandDiff = false,
}: {
  artifacts: readonly UiAgentBlock[];
  autoExpandDiff?: boolean;
}) {
  const visible = artifacts.filter((block) => block.type === 'file' || block.type === 'diff');
  if (!visible.length) return null;

  return (
    <div className="agent-tool-artifacts" aria-label="工具产物">
      {visible.map((block) => {
        if (block.type === 'file') {
          const diff = isDiffFile(block.data);
          return (
            <section
              aria-label={diff ? '文件变更' : '文件产物'}
              className="agent-tool-artifact-output"
              key={block.id}
            >
              <AgentFileBlock autoExpand={diff && autoExpandDiff} data={block.data} />
            </section>
          );
        }
        return (
          <section className="agent-tool-specialized-output" aria-label="文件变更" key={block.id}>
            <DiffPreview
              content={String(block.data.diff ?? block.data.text ?? '')}
              fileName={String(block.data.fileName ?? block.data.title ?? '')}
            />
          </section>
        );
      })}
    </div>
  );
}

export function hasToolArtifacts(artifacts: readonly UiAgentBlock[]): boolean {
  return artifacts.some((block) => block.type === 'file' || block.type === 'diff');
}

function isDiffFile(data: Record<string, unknown>): boolean {
  const mimeType = String(data.mimeType ?? '').toLowerCase();
  const fileName = String(data.fileName ?? data.name ?? '');
  return mimeType === 'text/x-diff'
    || mimeType === 'text/x-patch'
    || /\.(?:diff|patch)$/iu.test(fileName);
}
