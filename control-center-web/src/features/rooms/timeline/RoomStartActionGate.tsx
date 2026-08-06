import { LoaderCircle, Play } from 'lucide-react';

import { Button } from '@/components/primitives';
import type { RoomKernelReceiptV1 } from '@/contracts/generated/room-kernel-receipt.v1';
import type { RootProjection } from '@/contracts/room-kernel-reducer';

export interface RoomExecutionPlanFeature {
  title: string;
  participantRef?: string;
  ownerDisplayName: string;
  userOutcome: string;
  dependencies: string[];
  wave?: number;
  writeBoundary: string;
}

export interface RoomExecutionPlan {
  sharedContracts: string[];
  featureTasks: RoomExecutionPlanFeature[];
  integrationPlan: string;
  acceptancePlan: string[];
  continuityPlan: string;
}

export function roomRootRequiresStartAction(
  root: RootProjection | undefined,
  receipts: readonly RoomKernelReceiptV1[],
): boolean {
  if (!root || root.state !== 'waiting') return false;
  const authoritative = receipts.filter((receipt) => (
    receipt.rootId === root.rootId
    && receipt.generation === root.generation
    && receipt.status === 'applied'
  ));
  const definition = [...authoritative]
    .filter((receipt) => receipt.details.operation === 'room_define')
    .sort((left, right) => (
      right.createdAtMs - left.createdAtMs
      || right.receiptId.localeCompare(left.receiptId)
    ))[0];
  if (definition?.details.requiresStartAction !== true) return false;
  const latestIntake = [...authoritative]
    .filter((receipt) => receipt.details.purpose === 'intake_phase')
    .sort((left, right) => (
      right.createdAtMs - left.createdAtMs
      || right.receiptId.localeCompare(left.receiptId)
    ))[0];
  return latestIntake?.details.phase === 'awaiting_start';
}

export function roomRootExecutionPlan(
  root: RootProjection | undefined,
  receipts: readonly RoomKernelReceiptV1[],
): RoomExecutionPlan | undefined {
  if (!root) return undefined;
  const definition = [...receipts]
    .filter((receipt) => (
      receipt.rootId === root.rootId
      && receipt.generation === root.generation
      && receipt.status === 'applied'
      && receipt.details.operation === 'room_define'
    ))
    .sort((left, right) => (
      right.createdAtMs - left.createdAtMs
      || right.receiptId.localeCompare(left.receiptId)
    ))[0];
  const raw = definition?.details.executionPlan;
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return undefined;
  const source = raw as Record<string, unknown>;
  const featureTasks = Array.isArray(source.featureTasks)
    ? source.featureTasks.slice(0, 4).flatMap((value) => {
        if (!value || typeof value !== 'object' || Array.isArray(value)) return [];
        const feature = value as Record<string, unknown>;
        const title = cleanText(feature.title);
        const userOutcome = cleanText(feature.userOutcome);
        if (!title || !userOutcome) return [];
        return [{
          title,
          participantRef: cleanText(feature.participantRef) || undefined,
          ownerDisplayName: cleanText(feature.ownerDisplayName) || '待分配伙伴',
          userOutcome,
          dependencies: textList(feature.dependencies),
          wave: typeof feature.wave === 'number' && Number.isInteger(feature.wave)
            ? feature.wave
            : undefined,
          writeBoundary: cleanText(feature.writeBoundary),
        }];
      })
    : [];
  if (!featureTasks.length) return undefined;
  return {
    sharedContracts: textList(source.sharedContracts),
    featureTasks,
    integrationPlan: cleanText(source.integrationPlan),
    acceptancePlan: textList(source.acceptancePlan),
    continuityPlan: cleanText(source.continuityPlan),
  };
}

export function RoomStartActionGate({
  onStart,
  plan,
  starting,
}: {
  onStart: () => void;
  plan?: RoomExecutionPlan;
  starting: boolean;
}) {
  return <div aria-label="确认开始行动" className="room-start-action" role="group">
    <header>
      <strong>开始行动前，请确认这套分工</strong>
      <small>确认后才会让伙伴写代码、运行测试或进入后续任务。</small>
    </header>
    {plan ? <div className="room-start-action__plan">
      {plan.sharedContracts.length ? <section>
        <strong>所有功能先共同遵守</strong>
        <ul>{plan.sharedContracts.map((item) => <li key={item}>{item}</li>)}</ul>
      </section> : null}
      <section>
        <strong>各位伙伴分别交付</strong>
        <ol>{plan.featureTasks.map((feature) => <li key={`${feature.title}:${feature.ownerDisplayName}`}>
          <span><b>{feature.title}</b><small>{feature.wave ? `第 ${feature.wave} 波 · ` : ''}{feature.ownerDisplayName}</small></span>
          <p>{feature.userOutcome}</p>
          {feature.dependencies.length
            ? <small>开始条件：{feature.dependencies.join('、')}</small>
            : <small>无前置任务，可首批开始</small>}
          {feature.writeBoundary ? <small>这位伙伴负责：{feature.writeBoundary}</small> : null}
        </li>)}</ol>
      </section>
      {plan.continuityPlan ? <section>
        <strong>需求、进度和交接如何留存</strong><p>{plan.continuityPlan}</p>
      </section> : null}
      {plan.integrationPlan ? <section>
        <strong>伙伴如何合并结果</strong><p>{plan.integrationPlan}</p>
      </section> : null}
      {plan.acceptancePlan.length ? <section>
        <strong>你最终如何确认完成</strong>
        <ul>{plan.acceptancePlan.map((item) => <li key={item}>{item}</li>)}</ul>
      </section> : null}
    </div> : <p>当前任务作为一个端到端功能由负责人完成，完成后统一集成和验收。</p>}
    <footer>
      <span>你仍可先补充或调整分工。</span>
      <Button
        disabled={starting}
        leadingIcon={starting ? <LoaderCircle className="ui-spin" size={14} /> : <Play size={14} />}
        onClick={onStart}
        variant="primary"
      >{starting ? '正在开始' : '开始行动'}</Button>
    </footer>
  </div>;
}

function textList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.map(cleanText).filter(Boolean).slice(0, 16)
    : [];
}

function cleanText(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}
