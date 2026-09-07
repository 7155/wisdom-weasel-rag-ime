import { BrainCircuit, Search, Settings2, X } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';

import {
  Button,
  Input,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Select,
} from '@/components/primitives';
import {
  capabilityScopeLabel,
  type CapabilityCatalog,
  type CapabilityPreference,
} from '@/features/plugins/capability-policy';
import { openPawOsRoute, usePawOsDesktop } from '@/features/paw-os/surface-context';
import { CapabilityMark } from '../marks/ConversationMarks';
import type { SessionSummary, ToolManifest } from '../types';
import {
  countAvailableTools,
  countRegisteredTools,
  riskLabel,
  toolAvailableForConversation,
} from './tool-policy';
import './tool-picker.css';

export function ToolPicker({
  adjustmentDisabled,
  capabilityCatalog,
  capabilityPolicyPending,
  tools,
  status,
  session,
  disabled,
  requestOpen,
  requestQuery = '',
  onCapabilityPreferenceChange,
  onSelect,
}: {
  adjustmentDisabled: boolean;
  capabilityCatalog?: CapabilityCatalog;
  capabilityPolicyPending: boolean;
  tools: ToolManifest[];
  status: 'loading' | 'ready' | 'failed';
  session?: SessionSummary;
  disabled: boolean;
  requestOpen: number;
  requestQuery?: string;
  onCapabilityPreferenceChange: (canonicalId: string, preference: CapabilityPreference) => void;
  onSelect: (tool: ToolManifest) => void;
}) {
  const desktop = usePawOsDesktop();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const searchRef = useRef<HTMLInputElement>(null);
  const titleId = useId();
  useEffect(() => {
    if (requestOpen > 0 && status === 'ready' && !disabled) { setQuery(requestQuery); setOpen(true); }
  }, [disabled, requestOpen, requestQuery, status]);

  const memory = capabilityCatalog?.items.find((item) => item.canonicalId === 'tool:memory');
  const memoryEnabled = memory?.disclosure.effective === 'enabled';
  const availableCount = countAvailableTools(tools, session, capabilityCatalog);
  const registeredCount = countRegisteredTools(tools);
  const auxiliaryCapabilityCount = capabilityCatalog
    ? capabilityCatalog.items.filter((item) => item.kind !== 'tool').length
    : 0;
  const search = query.trim().toLocaleLowerCase();
  const visibleTools = tools.filter((tool) => {
    const presentation = toolPresentation(tool);
    return !search || [tool.id, tool.displayName, tool.description, presentation.name, presentation.description, tool.id === 'memory' ? '记忆自举 自动召回' : '']
      .some((value) => value.toLocaleLowerCase().includes(search));
  }).sort((left, right) => {
    if (!search) return 0;
    const byName = (tool: ToolManifest) => Number(toolPresentation(tool).name.toLocaleLowerCase().includes(search));
    return byName(right) - byName(left);
  });
  const label = status === 'loading'
    ? '能力列表正在读取'
    : status === 'failed'
      ? '能力列表暂不可用'
      : `这段对话可执行工具：${availableCount} 个；已登记工具：${registeredCount} 个`;
  const detail = status === 'loading'
    ? ' · 加载中'
    : status === 'failed'
      ? ' · 未加载'
      : ` · ${availableCount}/${registeredCount}`;

  return (
    <>
      {memory ? (
        <Button
          aria-label={`当前对话记忆${memoryEnabled ? '已开启' : '已关闭'}，打开记忆开关`}
          className="agent-composer__picker agent-composer__memory-picker"
          data-memory-enabled={memoryEnabled}
          disabled={disabled || status !== 'ready'}
          leadingIcon={<BrainCircuit size={15} />}
          onClick={() => { setQuery('记忆'); setOpen(true); }}
          size="small"
          title={`当前对话记忆${memoryEnabled ? '已开启' : '已关闭'} · ${capabilityScopeLabel(memory.effectiveScope)}；更改从下一轮生效`}
          variant="quiet"
        >记忆 · {memoryEnabled ? '开' : '关'}</Button>
      ) : null}
    <Popover open={open} onOpenChange={(nextOpen) => {
      setOpen(nextOpen);
      if (nextOpen) setQuery('');
    }}>
      <PopoverTrigger asChild>
        <Button
          aria-label={label}
          className="agent-composer__picker"
          data-effective-tool-count={availableCount}
          data-registered-tool-count={registeredCount}
          data-status={status}
          size="small"
          title={label}
          variant="quiet"
          disabled={status !== 'ready' || !tools.length || disabled}
          leadingIcon={<CapabilityMark size={16} />}
        >
          <span className="agent-composer__picker-text">工具</span>
          <span className="agent-composer__picker-detail">{detail}</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        aria-labelledby={titleId}
        className="agent-tool-picker"
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          searchRef.current?.focus();
        }}
      >
        <header className="agent-tool-picker__header">
          <div>
            <strong id={titleId}>当前对话工具</strong>
            <p>{availableCount} / {registeredCount} 项可用{auxiliaryCapabilityCount ? ` · 另有 ${auxiliaryCapabilityCount} 项技能与扩展` : ''}</p>
          </div>
          <button
            aria-label="关闭当前对话工具"
            className="agent-tool-picker__close"
            onClick={() => setOpen(false)}
            type="button"
          >
            <X aria-hidden="true" size={18} />
          </button>
        </header>
        <div className="agent-tool-picker__search">
          <Search aria-hidden="true" size={16} />
          <Input
            aria-label="搜索工具"
            autoComplete="off"
            onChange={(event) => setQuery(event.currentTarget.value)}
            placeholder="搜索工具，例如记忆、文件…"
            ref={searchRef}
            value={query}
          />
          {query ? (
            <button aria-label="清空工具搜索" className="agent-tool-picker__clear" onClick={() => {
              setQuery('');
              searchRef.current?.focus();
            }} type="button"><X aria-hidden="true" size={14} /></button>
          ) : null}
        </div>
        {adjustmentDisabled ? (
          <p className="agent-tool-picker__notice" data-tone="warning">
            当前任务正在运行；可以查看工具，但要等本轮结束后再调整。
          </p>
        ) : null}
        <div className="agent-tool-picker__list">
          {visibleTools.map((tool) => {
            const available = toolAvailableForConversation(tool, session, capabilityCatalog);
            const presentation = toolPresentation(tool);
            const capability = capabilityCatalog?.items.find(
              (item) => item.kind === 'tool' && item.id === tool.id,
            );
            return (
              <article className="agent-tool-picker__row" key={tool.id}>
                <div className="agent-tool-picker__heading">
                  <button
                    className="agent-tool-picker__name"
                    type="button"
                    disabled={!available || adjustmentDisabled}
                    title={`将${presentation.name}加入消息`}
                    onClick={() => {
                      setOpen(false);
                      onSelect(tool);
                    }}
                  >{presentation.name}</button>
                  {capability ? (
                    <span
                      className="agent-tool-picker__effective"
                      data-effective={capability.disclosure.effective}
                    >
                      {capability.disclosure.effective === 'disabled' ? '已关闭' : available ? '已启用' : '暂不可用'}
                    </span>
                  ) : null}
                </div>
                <p className="agent-tool-picker__description">{presentation.description}</p>
                <div className="agent-tool-picker__preference">
                  <div className="agent-tool-picker__metadata">
                    <span data-risk={tool.riskLevel}>{available ? riskLabel(tool.riskLevel) : '当前对话不可用'}</span>
                    {capability ? <span>{capabilityScopeLabel(capability.effectiveScope)}</span> : null}
                    {capability && capabilityCatalog?.sessionPolicy?.disclosurePreferences.globalDefault[capability.canonicalId]
                      && capabilityCatalog.sessionPolicy.disclosurePreferences.globalDefault[capability.canonicalId] !== 'inherit'
                      ? <span>所有对话默认：{capabilityCatalog.sessionPolicy.disclosurePreferences.globalDefault[capability.canonicalId] === 'enabled' ? '开启' : '关闭'}</span>
                      : null}
                  </div>
                  {capability ? (
                    <Select
                      aria-label={`${presentation.name}的当前对话使用`}
                      disabled={adjustmentDisabled || capabilityPolicyPending}
                      onValueChange={(preference) => onCapabilityPreferenceChange(capability.canonicalId, preference)}
                      options={capabilityUsagePreferenceOptions}
                      value={capabilityCatalog?.sessionPolicy?.disclosurePreferences.session[capability.canonicalId] ?? 'inherit'}
                    />
                  ) : null}
                </div>
              </article>
            );
          })}
          {!visibleTools.length ? (
            <div className="agent-tool-picker__empty" role="status">
              <strong>没有找到工具</strong>
              <p>换个名称或用途试试，也可以清空搜索查看全部。</p>
            </div>
          ) : null}
        </div>
        <p className="agent-tool-picker__note">
          更改从下一轮生效，后台任务继续运行。
        </p>
        <Button
          className="agent-tool-picker__manage"
          leadingIcon={<Settings2 size={14} />}
          onClick={() => {
            setOpen(false);
            const params = new URLSearchParams({ view: 'capabilities' });
            if (session?.id) params.set('sessionId', session.id);
            if (query.includes('记忆')) params.set('capability', 'tool:memory');
            openPawOsRoute(desktop, `/plugins?${params.toString()}`);
          }}
          size="small"
          variant="quiet"
        >管理功能与默认设置</Button>
      </PopoverContent>
    </Popover>
    </>
  );
}

const capabilityUsagePreferenceOptions = [
  { value: 'inherit', label: '跟随默认' },
  { value: 'enabled', label: '当前对话启用' },
  { value: 'disabled', label: '当前对话关闭' },
] as const;

function toolPresentation(tool: ToolManifest): { name: string; description: string } {
  if (tool.id === 'memory') {
    return {
      name: '记忆召回',
      description: '把相关记忆加入对话，并允许 Agent 查询记忆。关闭后从下一轮停止使用；不会删除已保存的记忆。',
    };
  }
  if (tool.id === 'knowledge') {
    return {
      name: '知识库 / Agent RAG',
      description: '启用后，Agent 可按当前问题反复检索已允许的知识库。',
    };
  }
  return { name: tool.displayName, description: tool.description };
}
