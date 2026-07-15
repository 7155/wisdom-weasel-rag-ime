import { useRef } from 'react';
import type { ControlTransport, ApprovedExternalActionId } from '@/platform/transport';
import {
  ManagementMutationWorkflow,
  parseManagementWorkPreview,
  parseManagementWorkReceipt,
  type ManagementWorkPreview,
  type ManagementWorkReceipt,
  type MutationAvailability,
} from '@/features/overview/management-mutation';
import { asRecord, stringValue } from '@/features/overview/management-ui';

export type DiagnosticsRuntimeAction =
  | 'register_input_source'
  | 'restart_sidecar'
  | 'restart_predictor'
  | 'redeploy_rime'
  | 'open_accessibility_settings'
  | 'stop_ai'
  | 'resume_ai';

type RuntimeActionContext = {
  action: DiagnosticsRuntimeAction;
  commandSha256: string;
  externalSupervisorRequired: boolean;
};

const applyPathId = 'diagnostics.action.start';
const externalActions = new Set<DiagnosticsRuntimeAction>([
  'register_input_source',
  'restart_sidecar',
  'restart_predictor',
  'redeploy_rime',
  'open_accessibility_settings',
]);

export function DiagnosticsRuntimeWorkflow({
  action,
  description,
  nativeExternalActions,
  onApplied,
  risk,
  runtimeRevision,
  title,
  transport,
}: {
  action: DiagnosticsRuntimeAction;
  description: string;
  nativeExternalActions: boolean;
  onApplied: () => void;
  risk: 'R1' | 'R2' | 'R3';
  runtimeRevision: number;
  title: string;
  transport: ControlTransport;
}) {
  const activeJobs = useRef(new Map<string, string>());
  const needsNativeBridge = externalActions.has(action);
  const availability: MutationAvailability = needsNativeBridge && (!nativeExternalActions || !transport.runApprovedExternalAction)
    ? { state: 'unsupported', reason: '这项本机操作只能由控制中心宿主的固定白名单执行。' }
    : Number.isInteger(runtimeRevision) && runtimeRevision >= 0
      ? { state: 'available' }
      : { state: 'blocked', reason: '等待后台返回当前运行版本后才能生成安全预览。' };

  return (
    <ManagementMutationWorkflow
      availability={availability}
      description={description}
      draftKey={`${action}:${runtimeRevision}`}
      mutationKey={['diagnostics', 'runtime-action', action]}
      onApply={async (preview) => {
        let jobId = activeJobs.current.get(preview.previewToken) ?? '';
        let receipt: ManagementWorkReceipt;
        if (!jobId) {
          const response = await transport.request({
            pathId: 'diagnostics.action.start',
            body: {
              action: preview.context.action,
              expectedRuntimeRevision: preview.expectedRuntimeRevision,
              previewToken: preview.previewToken,
              payloadSha256: preview.payloadSha256,
              commandSha256: preview.context.commandSha256,
              confirmText: preview.requiredConfirm,
            },
          });
          receipt = parseManagementWorkReceipt(response, applyPathId, preview.payloadSha256);
          jobId = stringValue(asRecord(receipt.raw.result).jobId);
          if (!jobId) throw new Error('后台没有返回可追踪的修复任务，请重新预览。');
          activeJobs.current.set(preview.previewToken, jobId);
        } else {
          receipt = {
            appliedAtMs: Date.now(),
            pathId: applyPathId,
            payloadSha256: preview.payloadSha256,
            receiptId: jobId,
            rollbackAvailable: false,
            rollbackToken: '',
            raw: {},
          };
        }

        await waitForRuntimeJob({ jobId, preview, transport });
        activeJobs.current.delete(preview.previewToken);
        return receipt;
      }}
      onApplied={onApplied}
      onPreview={async () => {
        const response = await transport.request({
          pathId: 'diagnostics.action.preview',
          body: { action, expectedRuntimeRevision: runtimeRevision },
        });
        return parseRuntimeActionPreview(response, action);
      }}
      risk={risk}
      title={title}
    />
  );
}

function parseRuntimeActionPreview(
  value: unknown,
  action: DiagnosticsRuntimeAction,
): ManagementWorkPreview<RuntimeActionContext> {
  const payload = asRecord(value);
  const commandSha256 = stringValue(payload.commandSha256);
  const returnedAction = stringValue(payload.action);
  const externalSupervisorRequired = payload.externalSupervisorRequired === true;
  if (returnedAction !== action || !/^sha256:[a-f0-9]{64}$/.test(commandSha256)) {
    throw new Error('后台返回的操作预览没有绑定到当前修复动作。');
  }
  if (externalSupervisorRequired !== externalActions.has(action)) {
    throw new Error('后台返回的操作执行边界与当前应用不一致。');
  }
  return parseManagementWorkPreview(
    payload,
    applyPathId,
    { action, commandSha256, externalSupervisorRequired },
  );
}

async function waitForRuntimeJob({
  jobId,
  preview,
  transport,
}: {
  jobId: string;
  preview: ManagementWorkPreview<RuntimeActionContext>;
  transport: ControlTransport;
}): Promise<void> {
  const deadline = Date.now() + 95_000;
  while (Date.now() < deadline) {
    const response = asRecord(await transport.request({
      pathId: 'diagnostics.action.job',
      params: { jobId },
    }));
    if (response.ok !== true) throw new Error(stringValue(response.error, '修复任务已不存在，请重新预览。'));
    const job = asRecord(response.job);
    if (stringValue(job.jobId) !== jobId || stringValue(job.action) !== preview.context.action) {
      throw new Error('后台返回了不匹配的修复任务。');
    }
    const status = stringValue(job.status);
    if (status === 'succeeded') return;
    if (status === 'external-supervisor-required') {
      await runExternalSupervisor(job, preview, transport);
      return;
    }
    if (status === 'failed' || status === 'timed_out') {
      const result = asRecord(job.result);
      const detail = stringValue(job.error, stringValue(result.stderr));
      throw new Error(detail || (status === 'timed_out' ? '修复任务执行超时，请重新预览后重试。' : '修复任务执行失败，请重新预览后重试。'));
    }
    if (status !== 'queued' && status !== 'running') {
      throw new Error('后台返回了无法识别的修复任务状态。');
    }
    await delay(250);
  }
  throw new Error('修复任务等待超时。任务可能仍在后台运行，可以稍后重试查看结果。');
}

async function runExternalSupervisor(
  job: Record<string, unknown>,
  preview: ManagementWorkPreview<RuntimeActionContext>,
  transport: ControlTransport,
): Promise<void> {
  if (!preview.context.externalSupervisorRequired || !transport.runApprovedExternalAction) {
    throw new Error('当前应用不能执行这项本机修复。');
  }
  const external = asRecord(asRecord(job.result).externalAction);
  const receiptId = stringValue(external.receiptId);
  const action = stringValue(external.action);
  const payloadSha256 = stringValue(external.payloadSha256);
  const commandSha256 = stringValue(external.commandSha256);
  if (
    receiptId !== stringValue(job.jobId)
    || action !== preview.context.action
    || payloadSha256 !== preview.payloadSha256
    || commandSha256 !== preview.context.commandSha256
  ) {
    throw new Error('外部修复回执没有通过预览绑定校验。');
  }
  const receipt = await transport.runApprovedExternalAction({
    action: action as ApprovedExternalActionId,
    receiptId,
    payloadSha256: stripSha256Prefix(payloadSha256),
    commandSha256: stripSha256Prefix(commandSha256),
  });
  if (
    receipt.receiptId !== receiptId
    || receipt.action !== action
    || !receipt.accepted
    || !receipt.completed
    || receipt.exitCode !== 0
  ) {
    throw new Error(receipt.error || '本机修复没有成功完成，可以重新预览后重试。');
  }
}

function stripSha256Prefix(value: string): string {
  const digest = value.startsWith('sha256:') ? value.slice(7) : value;
  if (!/^[a-f0-9]{64}$/.test(digest)) throw new Error('修复操作缺少有效的审批摘要。');
  return digest;
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}
