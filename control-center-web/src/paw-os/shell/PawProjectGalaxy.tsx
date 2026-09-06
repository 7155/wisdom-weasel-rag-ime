import { ArrowLeft, ArrowUpRight, ChevronLeft, ChevronRight, FileText, List, Pause, Play, Search, Settings2, X } from 'lucide-react';
import { Suspense, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/primitives/Dialog';
import { PawProjectGalaxyScene } from './PawProjectGalaxyScene';
import { assignGalaxySurfaces, projectGalaxyScene } from './project-galaxy-model';
import type { WayfinderWorkItem, WayfinderWorkProject } from './wayfinder-work-projection';
import './paw-project-galaxy.css';

export type PawProjectGalaxyProps = {
  project: WayfinderWorkProject;
  onClose(): void;
  onOpen(item: WayfinderWorkItem): void;
  onOpenProject(): void;
  onShowList?(): void;
  documents: ReactNode;
  modelDetails?(item: WayfinderWorkItem): ReactNode;
};
const pageSize = 12;

/** Project navigation over its own 3D universe. No independent Runtime reads. */
export function PawProjectGalaxy({ project, onClose, onOpen, onOpenProject, onShowList, documents, modelDetails }: PawProjectGalaxyProps) {
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(0);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [inspector, setInspector] = useState<'planet' | 'docs' | null>(null);
  const [webgl, setWebgl] = useState(true);
  const [paused, setPaused] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [visible, setVisible] = useState(() => document.visibilityState !== 'hidden');
  useEffect(() => {
    document.documentElement.dataset.pawProjectGalaxy = 'open';
    return () => { delete document.documentElement.dataset.pawProjectGalaxy; };
  }, []);
  useEffect(() => {
    const update = () => setVisible(document.visibilityState !== 'hidden');
    document.addEventListener('visibilitychange', update);
    return () => document.removeEventListener('visibilitychange', update);
  }, []);
  useEffect(() => { setPage(0); setSelectedKey(null); setQuery(''); setInspector(null); }, [project.id]);
  const matched = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return project.items.filter((item) => !needle || `${item.title}\n${item.statusLabel}\n${item.detail}`.toLocaleLowerCase().includes(needle))
      .sort((left, right) => left.key.localeCompare(right.key));
  }, [project.items, query]);
  const pageCount = Math.max(1, Math.ceil(matched.length / pageSize));
  const activePage = Math.min(page, pageCount - 1);
  const visibleItems = useMemo(() => matched.slice(activePage * pageSize, (activePage + 1) * pageSize), [matched, activePage]);
  const selected = visibleItems.find((item) => item.key === selectedKey);
  const surfaces = useMemo(() => new Map<string, number>(), [project.id]);
  const model = useMemo(() => projectGalaxyScene(project.id, project.label, visibleItems, assignGalaxySurfaces(project.items, surfaces)), [project.id, project.label, project.items, visibleItems, surfaces]);
  const pick = (key: string | null) => {
    if (key === null) { setSelectedKey(null); setInspector(null); return; }
    if (key === 'center') { setInspector('docs'); return; }
    if (key && visibleItems.some((item) => item.key === key)) { setSelectedKey(key); setInspector('planet'); }
  };
  const changePage = (next: number) => { setPage(next); setSelectedKey(null); setInspector(null); };

  return <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
    <DialogContent className="paw-project-galaxy" data-ambient={visible} data-inspector={inspector ?? 'closed'} data-design="painted-spiral" hideClose>
      <header className="paw-project-galaxy__header">
        <button aria-label="返回桌面" className="paw-project-galaxy__back" onClick={onClose} type="button"><ArrowLeft size={19} /><span>桌面</span></button>
        <div className="paw-project-galaxy__heading">
          <DialogTitle aria-label={`${project.label || '未绑定项目'} · 项目星系`}><span>{project.label || '未绑定项目'}</span><span className="paw-project-galaxy__title-suffix"> · 项目星系</span></DialogTitle>
          <DialogDescription>{project.items.length} 个对话 · {project.runningCount} 个运行中 · {project.attentionCount} 个待处理</DialogDescription>
        </div>
        <div className="paw-project-galaxy__header-actions">
          <button aria-label="项目 docs" aria-expanded={inspector === 'docs'} onClick={() => inspector === 'docs' ? pick(null) : pick('center')} type="button"><FileText size={17} /><span>项目 docs</span></button>
          {onShowList ? <button aria-label="文字列表" onClick={onShowList} title="文字列表" type="button"><List size={19} /></button> : null}
          <button aria-label="项目设置" onClick={onOpenProject} title="项目设置" type="button"><Settings2 size={18} /></button>
        </div>
      </header>
      <div className="paw-project-galaxy__workspace">
        <section aria-label="项目行星地图" className="paw-project-galaxy__map">
          <div className="paw-project-galaxy__sky">
            {webgl ? <PawProjectGalaxyScene key={project.id} model={model} running={visible} speed={paused ? 0 : speed} selectedId={inspector === 'docs' ? 'center' : selectedKey}
              onPick={pick} onFallback={() => setWebgl(false)} />
              : <div className="paw-project-galaxy__fallback">
                <p>当前设备无法加载 3D 星系。你仍可选择对话，查看进度与项目文档。</p>
                <div>{visibleItems.map((item) => <button aria-pressed={selectedKey === item.key} data-running={item.runtimeRunning} key={item.key} onClick={() => pick(item.key)} type="button">
                  <strong>{item.title}</strong><span>{item.statusLabel}{item.runtimeRunning && item.activity !== 'running' ? ' · 运行中' : ''}</span>
                  {item.progress ? <span>{item.progress.completed}/{item.progress.total} 项</span> : null}<small>{item.detail || '暂无公开进度'}</small>
                </button>)}</div>
              </div>}
            {!visibleItems.length ? <p className="paw-project-galaxy__empty">{query ? '没有匹配的对话。换一个标题或进度关键词。' : '这个项目还没有对话。可以先从项目 docs 开始。'}</p> : null}
          </div>
          <footer className="paw-project-galaxy__map-footer">
            <div className="paw-project-galaxy__navigation-hint"><span>{inspector ? '此刻，停留在这片星光' : '选择一簇星光，继续你的工作'}</span>{webgl ? <><small>{inspector ? '点击空白处返回星图' : '拖拽环顾 · 滚动缩放'}</small><div className="paw-project-galaxy__simulation">
              <button type="button" aria-label={paused ? '继续轨道模拟' : '暂停轨道模拟'} aria-pressed={paused} onClick={() => setPaused(!paused)}>{paused ? <Play size={13} /> : <Pause size={13} />}</button>
              <span>星系流动</span><select aria-label="模拟时间倍率" value={speed} onChange={(event) => setSpeed(Number(event.target.value))}><option value={.25}>0.25×</option><option value={1}>1×</option><option value={4}>4×</option></select>
            </div></> : null}</div>
            <div className="paw-project-galaxy__map-tools">
              {project.items.length > pageSize || query ? <label className="paw-project-galaxy__search"><Search aria-hidden="true" size={15} /><input aria-label="搜索项目对话" onChange={(event) => { setQuery(event.target.value); changePage(0); }} placeholder="搜索对话或进度" type="search" value={query} /></label> : null}
              <nav aria-label="行星分页"><span>{matched.length ? `${activePage * pageSize + 1}–${Math.min((activePage + 1) * pageSize, matched.length)}` : '0'} / {matched.length}</span>
                {pageCount > 1 ? <><button aria-label="上一组行星" disabled={activePage === 0} onClick={() => changePage(activePage - 1)} type="button"><ChevronLeft size={16} /></button><button aria-label="下一组行星" disabled={activePage + 1 === pageCount} onClick={() => changePage(activePage + 1)} type="button"><ChevronRight size={16} /></button></> : null}
              </nav>
            </div>
          </footer>
        </section>
        {inspector ? <aside aria-label="行星详情与项目文档" className="paw-project-galaxy__inspector" data-open={Boolean(inspector)}>
          {inspector ? <button className="paw-project-galaxy__close-inspector" aria-label="收起详情与项目文档" onClick={() => pick(null)} type="button"><X size={18} /></button> : null}
          {inspector === 'planet' && selected ? <section className="paw-project-galaxy__detail">
            <h2>{selected.title}</h2>
            <div className="paw-project-galaxy__detail-status" data-activity={selected.activity}><i />{selected.statusLabel}{selected.runtimeRunning ? <span>正在运行</span> : null}<span className="paw-project-galaxy__detail-type">{selected.kind === 'room' ? '协作 Room' : 'Agent 对话'}</span></div>
            <div className="paw-project-galaxy__model"><span>模型</span>{modelDetails?.(selected) ?? <span>模型未提供</span>}</div>
            <h3>当前进度</h3>
            {selected.progress ? <div className="paw-project-galaxy__completion"><span>已完成 {selected.progress.completed}/{selected.progress.total} 项</span><progress aria-label="协作任务完成进度" max={selected.progress.total} value={selected.progress.completed} /></div> : null}
            <p>{selected.detail || '暂无公开进度'}</p>
            {selected.agents.length ? <p>参与行星：{selected.agents.join('、')}</p> : null}
            <button className="paw-project-galaxy__open" onClick={() => onOpen(selected)} type="button">打开{selected.kind === 'room' ? '协作' : '对话'}<ArrowUpRight size={16} /></button>
          </section> : null}
          {inspector ? <section className="paw-project-galaxy__documents" aria-label="项目文档"><h2><FileText size={17} />项目文档</h2><Suspense fallback={<p role="status">正在读取项目文档…</p>}>{documents}</Suspense></section> : null}
        </aside> : null}
      </div>
    </DialogContent>
  </Dialog>;
}
