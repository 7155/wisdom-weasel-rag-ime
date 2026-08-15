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
import { asRecord, publicErrorText, stringValue } from '@/features/overview/management-ui';

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
    ? { state: 'unsupported', reason: '请在已安装的应用中完成这项本机操作。' }
    : Number.isInteger(runtimeRevision) && runtimeRevision >= 0
      ? { state: 'available' }
      : { state: 'blocked', reason: '正在同步运行状态，完成后即可继续。' };

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
          try {
            receipt = parseManagementWorkReceipt(response, applyPathId, preview.payloadSha256);
          } catch (cause) {
            throw publicRuntimeError(cause, '无法确认这项本机操作，请重新检查后再试。');
          }
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
    throw new Error('无法确认这项本机操作，请重新检查后再试。');
  }
  if (externalSupervisorRequired !== externalActions.has(action)) {
    throw new Error('无法确认这项本机操作，请重新检查后再试。');
  }
  try {
    return parseManagementWorkPreview(
      payload,
      applyPathId,
      { action, commandSha256, externalSupervisorRequired },
    );
  } catch (cause) {
    throw publicRuntimeError(cause, '无法确认这项本机操作，请重新检查后再试。');
  }
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
    if (response.ok !== true) throw publicRuntimeError(response.error, '修复任务已不存在，请重新检查后再试。');
    const job = asRecord(response.job);
    if (stringValue(job.jobId) !== jobId || stringValue(job.action) !== preview.context.action) {
      throw new Error('本机修复状态与当前操作不一致，请重新检查后再试。');
    }
    const status = stringValue(job.status);
    if (status === 'succeeded') return;
    if (status === 'external-supervisor-required') {
      await runExternalSupervisor(job, preview, transport);
      return;
    }
    if (status === 'failed' || status === 'timed_out') {
      const result = asRecord(job.result);
      const fallback = status === 'timed_out'
        ? '本机操作等待超时，请重新检查后再试。'
        : '本机操作没有完成，请重新检查后再试。';
      throw publicRuntimeError(stringValue(job.error, stringValue(result.stderr)), fallback);
    }
    if (status !== 'queued' && status !== 'running') {
      throw new Error('本机修复状态暂时无法确认，请重新检查后再试。');
    }
    await delay(250);
  }
  throw new Error('本机操作等待超时。任务可能仍在进行中，请稍后重新检查。');
}

async function runExternalSupervisor(
  job: Record<string, unknown>,
  preview: ManagementWorkPreview<RuntimeActionContext>,
  transport: ControlTransport,
): Promise<void> {
  if (!preview.context.externalSupervisorRequired || !transport.runApprovedExternalAction) {
    throw new Error('请在已安装的应用中完成这项本机操作。');
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
    throw new Error('无法确认本机操作是否已完成，请重新检查后再试。');
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
    throw publicRuntimeError(receipt.error, '本机操作没有完成，请重新检查后再试。');
  }
}

function stripSha256Prefix(value: string): string {
  const digest = value.startsWith('sha256:') ? value.slice(7) : value;
  if (!/^[a-f0-9]{64}$/.test(digest)) throw new Error('无法确认这项本机操作，请重新检查后再试。');
  return digest;
}

function publicRuntimeError(value: unknown, fallback: string): Error {
  return new Error(publicErrorText(value, fallback));
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}
