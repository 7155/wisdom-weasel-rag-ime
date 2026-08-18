import { useQuery } from '@tanstack/react-query';
import {
  Bot,
  Braces,
  GitFork,
  Network,
  ShieldCheck,
  Wrench,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useControlTransport } from '@/app/control-transport';
import { Button } from '@/components/primitives';
import type { AgentTemplateV1 } from '@/contracts/generated/agent-template.v1';
import { ManagementSection, StatusBadge } from '@/features/overview/management-ui';

export function SubagentSettingsPanel({ highlighted = false }: { highlighted?: boolean }) {
  const navigate = useNavigate();
  const transport = useControlTransport();
  const templatesQuery = useQuery({
    queryKey: ['configuration', 'subagents', 'templates'],
    queryFn: ({ signal }) => transport.request({
      pathId: 'agent.subagents.templates',
      signal,
    }),
    staleTime: 60_000,
    retry: false,
  });
  const envelope = record(templatesQuery.data);
  const templates = Array.isArray(envelope.items)
    ? envelope.items.filter(isTemplate)
    : [];
  const maxParallel = Number(envelope.maxParallel) || 2;
  const maxDepth = Number(envelope.maxDepth) || 2;

  return (
    <div
      id="configuration-subagents"
      className="configuration-subagents"
      data-highlighted={highlighted || undefined}
      aria-label="子 Agent 设置"
    >
      <ManagementSection
        title="子 Agent"
        description="Session 是唯一运行时所有者；Room 伙伴调用同一套子 Agent 能力，只投影启动收据和运行图。"
      >
        <div className="configuration-subagents__summary">
          <div>
            <span><Network size={18} /></span>
            <p><strong>Session 运行树</strong><small>最多并行 {maxParallel} 个节点 · Pattern 深度 {maxDepth} 层</small></p>
          </div>
          <StatusBadge label={templatesQuery.error ? '目录读取失败' : templatesQuery.isPending ? '正在读取' : `${templates.length} 个模板可用`} tone={templatesQuery.error ? 'danger' : templatesQuery.isPending ? 'neutral' : 'success'} />
          <Button leadingIcon={<Network size={15} />} onClick={() => navigate('/agent?subagents=open')} size="small">打开子 Agent 工作台</Button>
        </div>

        <div className="configuration-subagents__rules" aria-label="子 Agent 运行边界">
          <article><GitFork size={17} /><span><strong>Fresh / Fork</strong><small>启动时选择新上下文，或从父 Session 的明确锚点分支。</small></span></article>
          <article><Wrench size={17} /><span><strong>工具随模板收窄</strong><small>可以进一步缩小工具集合；子节点不能扩大父 Session 的能力。</small></span></article>
          <article><ShieldCheck size={17} /><span><strong>目录与写权限分离</strong><small>只读模板继承可读取目录，但写文件、命令与外部操作仍由运行策略拦截。</small></span></article>
          <article><Braces size={17} /><span><strong>结构化终止</strong><small>返回结果必须通过 Schema；合同无效只标记该节点，等待修复或改派。</small></span></article>
        </div>

        {templatesQuery.error ? <p className="configuration-subagents__error" role="alert">模板目录暂时不可用；不会用空目录覆盖当前配置。</p> : null}
        {templates.length ? <div className="configuration-subagents__templates" aria-label="子 Agent 模板">
          {templates.map((template) => <article key={`${template.templateId}:${template.version}`}>
            <span><Bot size={16} /></span>
            <p><strong>{template.displayName}</strong><small>{template.summary}</small></p>
            <em>{template.defaultAccess === 'write' ? '可申请写入' : '只读'}</em>
          </article>)}
        </div> : null}
      </ManagementSection>
    </div>
  );
}

function isTemplate(value: unknown): value is AgentTemplateV1 {
  const item = record(value);
  return item.schemaVersion === 'rag-ime.agent-template.v1'
    && typeof item.templateId === 'string'
    && typeof item.displayName === 'string'
    && typeof item.summary === 'string';
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}
