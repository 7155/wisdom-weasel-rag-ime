import { Boxes, RefreshCw, Search, ShieldCheck, Wrench } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Button, EmptyState, Field, Input, SegmentedControl } from '@/components/primitives';
import { usePluginCatalog } from './api';
import {
  ManagementPage,
  ManagementSection,
  MetricStrip,
  OperationalList,
  QueryState,
  StatusBadge,
  WorkflowAction,
  arrayRecords,
  asRecord,
  stringValue,
} from '@/features/overview/management-ui';

const riskFilters = ['all', 'R0', 'R1', 'R2', 'R3'] as const;

export function PluginsFeature() {
  const { catalog } = usePluginCatalog();
  const [query, setQuery] = useState('');
  const [risk, setRisk] = useState<typeof riskFilters[number]>('all');
  const items = arrayRecords(asRecord(catalog.data).items);
  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase('zh-CN');
    return items.filter((item) => {
      const haystack = [item.displayName, item.description, item.domain, ...(Array.isArray(item.operations) ? item.operations : [])]
        .map((value) => stringValue(value).toLocaleLowerCase('zh-CN'))
        .join(' ');
      return (!needle || haystack.includes(needle)) && (risk === 'all' || stringValue(item.riskLevel) === risk);
    });
  }, [items, query, risk]);
  const categories = new Set(items.map((item) => stringValue(item.category)).filter(Boolean));

  return (
    <ManagementPage
      actions={<Button leadingIcon={<RefreshCw size={15} />} loading={catalog.isFetching} onClick={() => void catalog.refetch()} size="small">刷新</Button>}
      description="查看可用 Tool、风险级别、Session 模式与受控能力范围。"
      eyebrow="TOOLS"
      routeId="plugins"
      title="插件与工具"
    >
      <QueryState error={catalog.error as Error | null} isPending={catalog.isPending} onRetry={() => void catalog.refetch()}>
        <ManagementSection title="目录状态">
          <MetricStrip items={[
            { label: '工具', value: items.length, detail: '已发现', icon: Wrench },
            { label: '在线', value: items.filter((item) => stringValue(item.availability) === 'online').length, detail: '当前可用', icon: ShieldCheck, tone: 'success' },
            { label: '领域', value: categories.size, detail: '能力分类', icon: Boxes },
            { label: '高风险', value: items.filter((item) => ['R2', 'R3'].includes(stringValue(item.riskLevel))).length, detail: '需要审批', icon: ShieldCheck, tone: 'warning' },
          ]} />
        </ManagementSection>

        <ManagementSection title="工具目录" description="按名称、领域与风险级别查找可用工具。">
          <div className="mgmt-filter-row">
            <Field htmlFor="plugin-search" label="搜索工具">
              <Input id="plugin-search" onChange={(event) => setQuery(event.target.value)} placeholder="名称、领域或操作" value={query} />
            </Field>
            <SegmentedControl aria-label="风险筛选" items={riskFilters.map((item) => ({ label: item === 'all' ? '全部' : item, value: item }))} onValueChange={setRisk} value={risk} />
          </div>
          {filtered.length ? (
            <OperationalList items={filtered.map((item) => ({
              id: stringValue(item.id),
              title: stringValue(item.displayName, stringValue(item.id)),
              detail: stringValue(item.description),
              meta: Array.isArray(item.operations) ? item.operations.map(String).join(' · ') : 'no operations',
              status: <StatusBadge label={`${stringValue(item.riskLevel, 'R0')} · ${stringValue(item.availability, 'unknown')}`} tone={stringValue(item.availability) === 'online' ? (['R2', 'R3'].includes(stringValue(item.riskLevel)) ? 'warning' : 'success') : 'danger'} />,
            }))} />
          ) : (
            <EmptyState description={items.length ? '没有工具符合当前筛选。' : '当前没有可用工具。'} icon={Search} title="没有匹配项" />
          )}
        </ManagementSection>

        <ManagementSection title="权限变更" description="当前为演练，不会修改工具权限。">
          <WorkflowAction
            actionId="plugins.permissions"
            description="调整工具在 assistant/coordinator Session 中的可用范围。"
            mutationKey={['plugins', 'mutation', 'permissions']}
            preview={[
              '只允许 manifest 中声明的 toolId 与 operation。',
              'R2/R3 操作仍需运行时逐次审批，catalog 开关不能绕过。',
              '工具界面不得绕过宿主权限边界。',
            ]}
            risk="R2"
            title="应用权限草案"
          />
        </ManagementSection>
      </QueryState>
    </ManagementPage>
  );
}
