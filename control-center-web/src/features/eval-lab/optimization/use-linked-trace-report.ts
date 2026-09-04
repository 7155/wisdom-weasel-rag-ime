import { useQuery } from '@tanstack/react-query';
import { useControlTransport } from '@/app/control-transport';
import type { TraceDiagnosticReportListV1 } from '@/contracts/generated/trace-diagnostic-report-list.v1';
import type { TraceDiagnosticReportV1 } from '@/contracts/generated/trace-diagnostic-report.v1';

type TraceReportSummary = TraceDiagnosticReportListV1['items'][number];

export function findLinkedTraceReportSummary(
  reports: readonly TraceReportSummary[],
  baselineRunId: string,
  baselineTraceIds: readonly string[],
): TraceReportSummary | undefined {
  const completed = reports
    .filter((report) => report.status === 'completed')
    .sort((left, right) => right.updatedAtMs - left.updatedAtMs);
  const runMatch = completed.find((report) => report.targets.some((target) => (
    target.kind === 'run' && target.id === baselineRunId
  )));
  if (runMatch) return runMatch;
  const traceIds = new Set(baselineTraceIds);
  if (!traceIds.size) return undefined;
  return completed.find((report) => report.traceIds.some((traceId) => traceIds.has(traceId)));
}

export function useLinkedTraceReport(input: {
  baselineRunId: string;
  baselineTraceIds: readonly string[];
}) {
  const transport = useControlTransport();
  const identityKey = [...input.baselineTraceIds].sort().join('|');
  const reports = useQuery<TraceDiagnosticReportListV1>({
    queryKey: ['eval-lab', 'optimization', 'trace-reports', input.baselineRunId, identityKey],
    queryFn: ({ signal }) => transport.request<TraceDiagnosticReportListV1>({
      pathId: 'observability.traceDiagnosticReports.list',
      query: { limit: 100 },
      responseContract: 'trace-diagnostic-report-list.v1',
      signal,
    }),
    retry: false,
    refetchOnWindowFocus: false,
  });
  const summary = findLinkedTraceReportSummary(
    reports.data?.items ?? [],
    input.baselineRunId,
    input.baselineTraceIds,
  );
  const report = useQuery<TraceDiagnosticReportV1>({
    queryKey: ['eval-lab', 'optimization', 'trace-report', summary?.reportId ?? 'unbound'],
    enabled: Boolean(summary?.reportId),
    queryFn: ({ signal }) => transport.request<TraceDiagnosticReportV1>({
      pathId: 'observability.traceDiagnosticReport.get',
      params: { reportId: summary!.reportId },
      responseContract: 'trace-diagnostic-report.v1',
      signal,
    }),
    retry: false,
    refetchOnWindowFocus: false,
  });

  return {
    error: reports.error ?? report.error,
    isLoading: reports.isLoading || Boolean(summary && report.isLoading),
    report: report.data,
  };
}
