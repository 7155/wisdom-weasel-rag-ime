import { BrainCircuit, Puzzle, Search, Settings2, X } from 'lucide-react';
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
  status: receivedStatus,
  session,
  sessionId = session?.id,
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
  /** A confirmed session catalog can be used by a Room without inventing a Session summary. */
  sessionId?: string;
  disabled: boolean;
  requestOpen: number;
  requestQuery?: string;
  onCapabilityPreferenceChange: (canonicalId: string, preference: CapabilityPreference) => void;
  onSelect: (tool: ToolManifest) => void;
}) {
  const catalogMatchesSession = !capabilityCatalog?.sessionPolicy
    || capabilityCatalog.sessionPolicy.sessionId === sessionId;
  const status = catalogMatchesSession ? receivedStatus : 'loading';
  const desktop = usePawOsDesktop();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [section, setSection] = useState<'tools' | 'plugins'>('tools');
  const searchRef = useRef<HTMLInputElement>(null);
  const titleId = useId();
  useEffect(() => {
    if (requestOpen > 0 && status === 'ready' && !disabled) { setSection('tools'); setQuery(requestQuery); setOpen(true); }
  }, [disabled, requestOpen, requestQuery, status]);

  const memory = catalogMatchesSession ? capabilityCatalog?.items.find((item) => item.canonicalId === 'tool:memory') : undefined;
  const memoryEnabled = memory?.disclosure.effective === 'enabled';
  useEffect(() => { if (!catalogMatchesSession) setOpen(false); }, [catalogMatchesSession]);
  const availableCount = countAvailableTools(tools, session, capabilityCatalog, sessionId);
  const registeredCount = countRegisteredTools(tools);
  const auxiliaryCapabilityCount = capabilityCatalog
    ? capabilityCatalog.items.filter((item) => item.kind !== 'tool').length
    : 0;
  const search = query.trim().toLocaleLowerCase();
  const plugins = capabilityCatalog?.items.filter((item) => item.kind !== 'tool') ?? [];
  const visiblePlugins = plugins.filter((item) => !search || [item.displayName, item.description, item.id, item.source.label]
    .some((value) => value.toLocaleLowerCase().includes(search)));
  const enabledPlugins = plugins.filter((item) => item.disclosure.effective === 'enabled' && item.authorization.state !== 'denied').length;
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
    <Popover open={open && catalogMatchesSession} onOpenChange={(nextOpen) => {
      setOpen(nextOpen);
      if (nextOpen) { setSection('tools'); setQuery(''); }
    }}>
      <PopoverTrigger asChild>
        <Button
          aria-label={`对话功能：记忆、工具、插件与技能；${label}`}
          className="agent-composer__picker"
          data-effective-tool-count={availableCount}
          data-registered-tool-count={registeredCount}
          data-status={status}
          size="small"
          title={label}
          variant="quiet"
          disabled={status !== 'ready' || disabled}
          leadingIcon={<CapabilityMark size={16} />}
        >
          <span className="agent-composer__picker-text">功能</span>
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
            <strong id={titleId}>{section === 'plugins' ? '当前对话插件与技能' : '当前对话工具'}</strong>
            <p>{section === 'plugins' ? `${enabledPlugins} / ${plugins.length} 项已开启` : `${availableCount} / ${registeredCount} 项可用${auxiliaryCapabilityCount ? ` · 另有 ${auxiliaryCapabilityCount} 项技能与扩展` : ''}`}</p>
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
        <div className="agent-tool-picker__categories" role="group" aria-label="对话功能分类">
          <Button
            aria-pressed={section === 'tools' && query !== '记忆'}
            className="agent-tool-picker__category"
            leadingIcon={<CapabilityMark size={16} />}
            onClick={() => { setSection('tools'); setQuery(''); }}
            size="small"
            variant="quiet"
          >工具 · {availableCount}/{registeredCount}</Button>
      {memory ? (
        <Button
          aria-label={`当前对话记忆${memoryEnabled ? '已开启' : '已关闭'}，打开记忆开关`}
          className="agent-tool-picker__category"
          aria-pressed={section === 'tools' && query === '记忆'}
          data-memory-enabled={memoryEnabled}
          disabled={disabled || status !== 'ready'}
          leadingIcon={<BrainCircuit size={15} />}
          onClick={() => { setSection('tools'); setQuery('记忆'); setOpen(true); }}
          size="small"
          title={`当前对话记忆${memoryEnabled ? '已开启' : '已关闭'} · ${capabilityScopeLabel(memory.effectiveScope)}；更改从下一轮生效`}
          variant="quiet"
        >记忆 · {memoryEnabled ? '开' : '关'}</Button>
      ) : null}
      <Button
        aria-label="当前对话插件与技能"
        aria-pressed={section === 'plugins'}
        className="agent-tool-picker__category"
        disabled={disabled || status !== 'ready'}
        leadingIcon={<Puzzle size={15} />}
        onClick={() => { setSection('plugins'); setQuery(''); setOpen(true); }}
        size="small"
        variant="quiet"
      >插件 · {status === 'ready' ? `${enabledPlugins}/${plugins.length}` : '加载中'}</Button>
        </div>
        <div className="agent-tool-picker__search">
          <Search aria-hidden="true" size={16} />
          <Input
            aria-label={section === 'plugins' ? '搜索插件与技能' : '搜索工具'}
            autoComplete="off"
            onChange={(event) => setQuery(event.currentTarget.value)}
            placeholder={section === 'plugins' ? '搜索插件或技能…' : '搜索工具，例如记忆、文件…'}
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
          {section === 'tools' && visibleTools.map((tool) => {
            const available = toolAvailableForConversation(tool, session, capabilityCatalog, sessionId);
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
          {section === 'plugins' && visiblePlugins.map((item) => (
            <article className="agent-tool-picker__row" key={item.canonicalId}>
              <div className="agent-tool-picker__heading">
                <strong>{item.displayName}</strong>
                <span className="agent-tool-picker__effective" data-effective={item.disclosure.effective}>
                  {item.disclosure.effective === 'disabled' ? '已关闭' : item.authorization.state === 'denied' ? '暂不可用' : '已启用'}
                </span>
              </div>
              <p className="agent-tool-picker__description">{item.description}</p>
              <div className="agent-tool-picker__preference">
                <div className="agent-tool-picker__metadata"><span>{item.kind === 'skill' ? '技能' : '扩展'}</span><span>{item.source.label}</span><span>{capabilityScopeLabel(item.effectiveScope)}</span></div>
                <Select
                  aria-label={`${item.displayName}的当前对话使用`}
                  disabled={adjustmentDisabled || capabilityPolicyPending || item.status === 'removed'}
                  options={capabilityUsagePreferenceOptions}
                  value={capabilityCatalog?.sessionPolicy?.disclosurePreferences.session[item.canonicalId] ?? 'inherit'}
                  onValueChange={(preference) => onCapabilityPreferenceChange(item.canonicalId, preference)}
                />
              </div>
            </article>
          ))}
          {!(section === 'plugins' ? visiblePlugins : visibleTools).length ? (
            <div className="agent-tool-picker__empty" role="status">
              <strong>{section === 'plugins' ? '没有找到插件或技能' : '没有找到工具'}</strong>
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
            if (sessionId) params.set('sessionId', sessionId);
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
