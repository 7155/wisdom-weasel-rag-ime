export type ApprovalDecisionMode = 'human' | 'policy' | 'model' | '';

export interface ApprovalDecisionView {
  mode: ApprovalDecisionMode;
  automatic: boolean;
  decision: 'approve' | 'deny' | '';
  status: string;
  model: string;
  receiptId: string;
  reasonCodes: string[];
  rationaleSummary: string;
  contextKind: 'session' | 'room' | '';
  contextId: string;
  historyEntryCount: number | null;
}

/**
 * Read the bounded approval-decision projection shared by Agent and Room SSE.
 * Backend revisions may carry it on the event or inside the public Tool result;
 * this adapter keeps UI behavior stable without inferring authority from prose.
 */
export function approvalDecisionView(value: unknown): ApprovalDecisionView {
  const payload = record(value);
  const carrier = record(payload.result ?? payload.publicResult);
  const details = record(carrier.details);
  const result = {
    ...carrier,
    ...details,
    ...record(details.result),
  };
  const approval = record(payload.approval ?? result.approval);
  const preview = record(payload.preview ?? result.preview ?? approval.preview);
  const arbitration = record(
    payload.approvalArbitration
    ?? result.approvalArbitration
    ?? approval.approvalArbitration
    ?? preview.approvalArbitration,
  );
  const decision = record(
    payload.approvalModelDecision
    ?? result.approvalModelDecision
    ?? approval.approvalModelDecision
    ?? preview.approvalModelDecision
    ?? payload.approvalDecision
    ?? result.approvalDecision
    ?? approval.approvalDecision
    ?? arbitration.decisionReceipt,
  );
  const explicitMode = firstText(
    payload.approvalDecisionMode,
    result.approvalDecisionMode,
    approval.approvalDecisionMode,
    preview.approvalDecisionMode,
    payload.decisionMode,
    result.decisionMode,
    approval.decisionMode,
    arbitration.mode,
    decision.decisionMode,
    decision.mode,
  ).toLowerCase();
  const model = firstText(
    decision.model,
    decision.modelProfile,
    arbitration.model,
    arbitration.modelProfile,
    payload.approvalModel,
    result.approvalModel,
    approval.approvalModel,
  );
  const mode: ApprovalDecisionMode = explicitMode === 'model'
    || (!explicitMode && Boolean(model))
    ? 'model'
    : explicitMode === 'policy'
      ? 'policy'
      : explicitMode === 'human'
        ? 'human'
        : '';
  const rawDecision = firstText(
    decision.decision,
    arbitration.decision,
    payload.modelDecision,
    result.modelDecision,
    approval.modelDecision,
    payload.decision,
  ).toLowerCase();
  const normalizedDecision = rawDecision === 'approved' ? 'approve'
    : rawDecision === 'rejected' || rawDecision === 'denied' ? 'deny'
      : rawDecision;
  const reasonValues = decision.reasonCodes
    ?? arbitration.reasonCodes
    ?? payload.reasonCodes
    ?? result.reasonCodes
    ?? approval.reasonCodes;
  return {
    mode,
    automatic: payload.automatic === true
      || result.automatic === true
      || payload.autoApproved === true
      || result.autoApproved === true
      || mode === 'policy'
      || mode === 'model',
    decision: normalizedDecision === 'approve' || normalizedDecision === 'deny'
      ? normalizedDecision
      : '',
    status: firstText(
      decision.status,
      arbitration.status,
      payload.modelDecisionStatus,
      result.modelDecisionStatus,
      approval.modelDecisionStatus,
      payload.decisionStatus,
      result.decisionStatus,
      approval.decisionStatus,
    ),
    model,
    receiptId: firstText(
      decision.receiptId,
      arbitration.receiptId,
      payload.approvalDecisionReceiptId,
      result.approvalDecisionReceiptId,
      approval.approvalDecisionReceiptId,
    ),
    reasonCodes: Array.isArray(reasonValues)
      ? reasonValues.flatMap((item) => typeof item === 'string' && item.trim() ? [item.trim()] : []).slice(0, 8)
      : [],
    rationaleSummary: firstText(
      decision.rationaleSummary,
      arbitration.rationaleSummary,
      payload.rationaleSummary,
      result.rationaleSummary,
      approval.rationaleSummary,
    ),
    contextKind: firstText(decision.contextKind) === 'room'
      ? 'room'
      : firstText(decision.contextKind) === 'session'
        ? 'session'
        : '',
    contextId: firstText(decision.contextId),
    historyEntryCount: finiteNonNegativeInteger(decision.historyEntryCount),
  };
}

export function approvalDecisionReasonLabel(reasonCode: string): string {
  return APPROVAL_REASON_LABELS[reasonCode] ?? reasonCode;
}

const APPROVAL_REASON_LABELS: Record<string, string> = {
  bounded_operation: '操作范围受限',
  authorized_scope: '工作区已授权',
  requested_effect_matches_preview: '效果与预览一致',
  destructive_effect: '包含破坏性操作',
  sensitive_target: '涉及敏感目标',
  network_effect: '包含网络影响',
  irreversible_effect: '影响不可逆',
  cross_workspace: '超出工作区',
  insufficient_evidence: '审批证据不足',
  scope_not_authorized: '范围未授权',
  prompt_injection_detected: '检测到提示注入风险',
  policy_boundary: '触及安全边界',
  model_timeout: '审批模型超时',
  model_unavailable: '审批模型不可用',
  model_invalid_response: '审批模型返回无效',
};


export function approvalNeedsHumanDecision(value: unknown): boolean {
  return !approvalDecisionView(value).automatic;
}

function firstText(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return '';
}

function finiteNonNegativeInteger(value: unknown): number | null {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0
    ? value
    : null;
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}
