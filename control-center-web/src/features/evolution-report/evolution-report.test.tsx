import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { EvolutionReportFeature } from './index';

afterEach(cleanup);

describe('EvolutionReportFeature', () => {
  it('explains each headline from raw measurements instead of showing a score-card summary', () => {
    render(<EvolutionReportFeature />);

    expect(screen.getByRole('heading', { name: '自我进化实验账本' })).toBeInTheDocument();
    expect(screen.getByText('这不是成绩单')).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: '报告章节' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '先理解：系统到底在做什么' })).toBeInTheDocument();
    expect(screen.getByText('RAG 是“先找资料，再回答”')).toBeInTheDocument();
    expect(screen.getByText('调参 Agent')).toBeInTheDocument();
    expect(screen.getByText('沙盒测试 Agent')).toBeInTheDocument();
    expect(screen.getByText('评价 Agent')).toBeInTheDocument();
    expect(screen.getByText('Keep / Reject 门禁')).toBeInTheDocument();
    expect(screen.getByText('nDCG@10 看排序质量')).toBeInTheDocument();
    expect(screen.getByText('MRR 看第一个正确答案有多靠前')).toBeInTheDocument();
    expect(screen.getByText('Recall@10 看前十条找回了多少应找资料')).toBeInTheDocument();

    const rag = screen.getByRole('region', { name: 'RAG 检索调优' });
    expect(within(rag).getByText('16 个 Validation query')).toBeInTheDocument();
    expect(within(rag).getByText('14 个候选配置')).toBeInTheDocument();
    expect(within(rag).getByText('0.6128 → 0.8872')).toBeInTheDocument();
    expect(within(rag).getByText('+44.78%')).toBeInTheDocument();
    expect(within(rag).getByText('+43.53%')).toBeInTheDocument();
    expect(within(rag).getByText('+42.19%')).toBeInTheDocument();
    expect(within(rag).getByText('Held-out 未打开')).toBeInTheDocument();

    const cloudOps = screen.getByRole('region', { name: 'CloudOps 工作流试验' });
    expect(within(cloudOps).getByText('Reject')).toBeInTheDocument();
    expect(within(cloudOps).getByText('98 → 189')).toBeInTheDocument();
    expect(within(cloudOps).getByText('+92.86%')).toBeInTheDocument();
    expect(within(cloudOps).getByText('−26.58%')).toBeInTheDocument();

    const trace = screen.getByRole('region', { name: 'Trace 缺陷闭环' });
    expect(within(trace).getByText('8 个闭环缺陷')).toBeInTheDocument();
    expect(within(trace).getByText('3 个主仓 Validation')).toBeInTheDocument();
    expect(within(trace).getByText('5 个源码候选复验')).toBeInTheDocument();
    expect(within(trace).getByText(/这些分类互有重叠，不能相加/)).toBeInTheDocument();
    expect(within(trace).getByText('以前的问题')).toBeInTheDocument();
    expect(within(trace).getByText('改了什么')).toBeInTheDocument();
    expect(within(trace).getByText('带来的效果')).toBeInTheDocument();

    const app = screen.getByRole('region', { name: '掌柜问数沙盒' });
    expect(within(app).getByText('1 个 SGG 固定夹具')).toBeInTheDocument();
    expect(within(app).getByText('Provider 调用 0')).toBeInTheDocument();
    expect(within(app).getByText('Spider 2.0-Lite 未正式评分')).toBeInTheDocument();

    const cache = screen.getByRole('region', { name: '上下文缓存 canary' });
    expect(within(cache).getByText('10,647')).toBeInTheDocument();
    expect(within(cache).getAllByText('9,728')).toHaveLength(2);
    expect(within(cache).getByRole('heading', { name: '正确结论：90.96%–91.16%' })).toBeInTheDocument();
    expect(within(cache).getByText(/上一版摘要中的 92\.7%–92\.9% 是抄录错误/)).toBeInTheDocument();
  });

  it('keeps claim boundaries and evidence locations visible without opening a disclosure', () => {
    render(<EvolutionReportFeature />);

    expect(screen.getAllByText('Validation-only').length).toBeGreaterThan(0);
    expect(screen.getByText(/不能写成生产提升/)).toBeInTheDocument();
    expect(screen.getByText(/不能写成生产 Text-to-SQL 准确率/)).toBeInTheDocument();
    expect(screen.getByText(/不能写成 Trace Agent 自动修复了全部 8 个问题/)).toBeInTheDocument();
    expect(screen.getByText('enterprise-rag-validation-20260831.v1.json')).toBeInTheDocument();
    expect(screen.getByText('cloudops-evidence-search-validation-reject-20260901.v1.json')).toBeInTheDocument();
    expect(screen.getByText('pi-context-cache-20260830.v1.json')).toBeInTheDocument();
  });

  it('scrolls between report chapters without replacing the PAWOS hash route', async () => {
    const user = userEvent.setup();
    window.location.hash = '#/evolution-report';
    render(<div className="paw-system-app__page"><EvolutionReportFeature /></div>);
    const target = document.getElementById('cloudops');
    const scrollOwner = document.querySelector('.paw-system-app__page') as HTMLElement;
    const scrollTo = vi.fn();
    Object.defineProperty(scrollOwner, 'scrollTop', { configurable: true, value: 120 });
    Object.defineProperty(scrollOwner, 'scrollTo', { configurable: true, value: scrollTo });
    target!.getBoundingClientRect = () => ({ top: 430 } as DOMRect);
    scrollOwner.getBoundingClientRect = () => ({ top: 70 } as DOMRect);

    await user.click(screen.getByRole('button', { name: 'CloudOps' }));

    expect(scrollTo).toHaveBeenCalledWith({ behavior: 'auto', top: 480 });
    expect(window.location.hash).toBe('#/evolution-report');
  });
});
