import { useQuery } from '@tanstack/react-query';
import { useInRouterContext, useSearchParams } from 'react-router-dom';
import { useControlTransport } from '@/app/control-transport';
import { openPawOsRoute, usePawOsDesktop } from '@/features/paw-os/surface-context';
import type { TraceDiagnosticReportV1 } from '@/contracts/generated/trace-diagnostic-report.v1';
import type { EvalLabExperiment } from './api';

export function TraceLabContext({ experiment }: { experiment?: EvalLabExperiment }) {
  const routed = useInRouterContext();
  return routed ? <RoutedTraceLabContext experiment={experiment} /> : null;
}

function RoutedTraceLabContext({ experiment }: { experiment?: EvalLabExperiment }) {
  const [params] = useSearchParams();
  const reportId = params.get('traceReportId')?.trim() ?? '';
  const transport = useControlTransport();
  const desktop = usePawOsDesktop();
  const report = useQuery({
    queryKey: ['eval-lab', 'source-report', reportId],
    enabled: Boolean(reportId),
    queryFn: ({ signal }) => transport.request<TraceDiagnosticReportV1>({
      pathId: 'observability.traceDiagnosticReport.get',
      params: { reportId },
      responseContract: 'trace-diagnostic-report.v1',
      signal,
    }),
    retry: false,
    refetchOnWindowFocus: false,
  });
  if (!reportId) return null;
  const exactReport = report.data?.reportId === reportId ? report.data : undefined;
  const matched = Boolean(experiment && exactReport?.targets.some((target) => target.kind === 'run' && target.id === experiment.baseline.runId));
  return <aside aria-label="来源诊断" className="eval-lab__source-context">
    <div><strong>从单次诊断进入实验</strong>
      <p>{report.isLoading ? '正在读取来源诊断…' : report.error || !exactReport ? '来源诊断暂时无法读取，可返回原报告重试。' : exactReport.title}</p>
      {exactReport ? <small>{matched ? '来源报告与本实验的原运行精确关联。' : '来源报告尚未与本实验基线关联；选择实验不会自动建立证据关系。'}</small> : null}
    </div>
    <button onClick={() => openPawOsRoute(desktop, `/trace-agent?reportId=${encodeURIComponent(reportId)}`)} type="button">返回来源诊断</button>
  </aside>;
}
