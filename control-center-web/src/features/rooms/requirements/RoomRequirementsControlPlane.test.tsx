import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { RoomRequirementsControlPlane } from './RoomRequirementsControlPlane';
import {
  parseRoomRequirementsReadProjection,
  type RoomRequirementsReadProjection,
} from './room-requirements-read-model';

describe('RoomRequirementsControlPlane', () => {
  afterEach(cleanup);

  it('keeps long original requirements read-only and names acceptance criteria in user language', async () => {
    const longText = `原始需求不可修改。\n${'保留完整上下文和换行。'.repeat(180)}`;
    const projection = fixture({ originalText: longText, originalHash: '0'.repeat(64), originalBytes: new TextEncoder().encode(longText).byteLength });
    render(<RoomRequirementsControlPlane projection={projection} />);

    const original = screen.getByLabelText('第 1 条原始需求只读文本');
    expect(original).toHaveTextContent('原始需求不可修改');
    expect(original).toHaveAttribute('tabindex', '0');
    original.focus();
    expect(original).toHaveFocus();
    expect(screen.getByText('验收标准')).toBeInTheDocument();
    expect(screen.getByText(/永久保留，不可修改/)).toBeInTheDocument();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /编辑|保存|修改/ })).not.toBeInTheDocument();
    expect(screen.getByText('原文校验失败')).toBeInTheDocument();
  });

  it('reports verified original text without exposing its content hash', async () => {
    render(<RoomRequirementsControlPlane projection={fixture()} />);
    expect(screen.getByText('abc')).toBeInTheDocument();
    expect(screen.getAllByText('原文完整性已核验').length).toBeGreaterThan(0);
    expect(screen.queryByText('ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')).not.toBeInTheDocument();
  });

  it('distinguishes the enforced Kernel settlement gate from observe-only delivery checks', () => {
    const pass = fixture();
    const { container, rerender } = render(<RoomRequirementsControlPlane projection={pass} />);
    expect(container.querySelector('[data-gate-status="enforced"]')).toHaveTextContent('任务收工检查');
    expect(screen.getByText('始终启用')).toBeInTheDocument();
    expect(screen.getByText(/系统会拒绝收工/)).toBeInTheDocument();
    expect(container.querySelector('[data-gate-status="observed_pass"]')).toBeInTheDocument();
    expect(container.querySelector('[data-gate-status="observed_pass"] [data-status="observed_pass"]')).toHaveTextContent('已观察通过');
    expect(screen.getByText(/不会在生产环境额外增加一道终态拦截/)).toBeInTheDocument();
    expect(screen.queryByText('预览：强制拦截')).not.toBeInTheDocument();

    const warning = fixture({ gateStatus: 'warn_blocked', reasons: ['unresolved_unknown', 'unresolved_blocker', 'user_journey_missing', 'blind_review_not_passed'] });
    rerender(<RoomRequirementsControlPlane projection={warning} />);
    expect(container.querySelector('[data-gate-status="warn_blocked"]')).toBeInTheDocument();
    expect(container.querySelector('[data-gate-status="warn_blocked"] [data-status="observed_pass"]')).toBeNull();
    expect(screen.getAllByText(/未知项未解决|阻塞项未解决|用户旅程缺失|盲审未通过/).length).toBeGreaterThan(0);
  });

  it('fails closed for a tampered issuer, old revision, and wrong commit', () => {
    const tampered = fixture({ proofStatus: 'tampered', proofReasons: ['untrusted_verifier'] });
    render(<RoomRequirementsControlPlane projection={tampered} />);
    const proof = screen.getByRole('region', { name: '验证记录' });
    expect(within(proof).getByText('记录不可信')).toHaveAttribute('data-status', 'tampered');
    expect(within(proof).getByText('签发者不可信')).toBeInTheDocument();

    const stale = fixture({ proofStatus: 'stale', proofReasons: ['old_catalog_revision', 'wrong_commit'] });
    expect(stale.receiptAssessments[0]).toMatchObject({ status: 'stale', reasons: ['old_catalog_revision', 'wrong_commit'] });
  });

  it('keeps concurrent task projections isolated without exposing protocol identifiers', () => {
    render(<>
      <RoomRequirementsControlPlane projection={fixture()} />
      <RoomRequirementsControlPlane projection={fixture({ rootId: 'root-b', originalText: '另一项原始需求', originalHash: '0'.repeat(64), originalBytes: 13 })} />
    </>);
    expect(screen.getAllByRole('region', { name: '需求、证明与审查' })).toHaveLength(2);
    expect(screen.getAllByText('第 1 项冲突')).toHaveLength(2);
    expect(screen.getAllByText('第 1 轮同伴复核')).toHaveLength(2);
    expect(screen.getAllByText(/1 位伙伴 · 已通过 · 通过 · 验证记录已保存/)).toHaveLength(2);
    expect(screen.queryByText('anchor-root-a')).not.toBeInTheDocument();
    expect(screen.queryByText('item-a ↔ item-b')).not.toBeInTheDocument();
    expect(screen.queryByText('peer-reviewer')).not.toBeInTheDocument();
    expect(screen.queryByText(/peer-receipt-1/)).not.toBeInTheDocument();
  });

  it('rejects malformed canonical input instead of turning Agent text into proof', () => {
    const raw = rawFixture();
    raw.receiptAssessments[0].receipt = { ...raw.receiptAssessments[0].receipt, outputHash: 'Agent says tests passed' };
    expect(() => parseRoomRequirementsReadProjection(raw)).toThrow(/typed-verification-receipt/);
    const crossRoot = rawFixture();
    crossRoot.anchors[0] = { ...crossRoot.anchors[0], anchor: { ...crossRoot.anchors[0]!.anchor, rootId: 'root-other' } };
    expect(() => parseRoomRequirementsReadProjection(crossRoot)).toThrow(/another Root/);
  });
});

type FixtureOptions = {
  rootId?: string;
  originalText?: string;
  originalHash?: string;
  originalBytes?: number;
  proofStatus?: 'observed_pass' | 'failed' | 'stale' | 'tampered';
  proofReasons?: string[];
  gateStatus?: 'observed_pass' | 'warn_blocked';
  reasons?: string[];
};

function fixture(options: FixtureOptions = {}): RoomRequirementsReadProjection {
  return parseRoomRequirementsReadProjection(rawFixture(options));
}

function rawFixture(options: FixtureOptions = {}) {
  const rootId = options.rootId ?? 'root-a';
  const anchorId = `anchor-${rootId}`;
  const catalogId = `catalog-${rootId}-r2`;
  const originalText = options.originalText ?? 'abc';
  return {
    projectionSource: 'canonical_fixture' as const,
    rootId,
    anchors: [{
      anchor: {
        schemaVersion: 'wisdom-weasel.requirement-anchor.v1', anchorId, rootId, rootSequence: 1,
        originalContentSha256: options.originalHash ?? 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
        originalByteLength: options.originalBytes ?? 3, createdBy: 'user:1', authenticity: 'original_user_bytes',
        provenance: { requestId: 'request-1' }, createdAtMs: 1,
      },
      originalText,
      integrityStatus: options.originalHash === '0'.repeat(64) ? 'tampered' : 'verified',
    }],
    catalog: {
      schemaVersion: 'wisdom-weasel.requirement-catalog-revision.v1', catalogRevisionId: catalogId, rootId, revision: 2,
      supersedesRevisionId: `catalog-${rootId}-r1`, anchorRefs: [anchorId],
      items: [{ itemId: 'item-a', statement: '保留用户原始需求', kind: 'explicit_user_requirement', state: 'active' }],
      acceptanceCriteria: [{ criterionId: 'criterion-a', itemId: 'item-a', acceptanceCriterionFullNameZh: '原始需求永久保留验收标准', criterionKind: 'user_journey', expectedReceiptTypes: ['test'], statement: '原文只读且哈希一致' }],
      changeReason: '拆分验收条件', provenance: { source: 'requirement-review' }, payloadHash: 'c'.repeat(64),
      createdBy: 'requirements-governor', createdAtMs: 2,
    },
    receiptAssessments: [{ receipt: {
      schemaVersion: 'wisdom-weasel.typed-verification-receipt.v1', receiptId: `receipt-${rootId}`, rootId,
      catalogRevisionId: catalogId, receiptType: 'test', sourceCommit: 'commit-current',
      environment: 'managed-ci', commandOrAction: 'pnpm test', exitStatus: 0, outputHash: 'd'.repeat(64),
      artifactHash: 'e'.repeat(64), verifier: 'managed-test-runner', createdAtMs: 3,
    }, status: options.proofStatus ?? 'observed_pass', reasons: options.proofReasons ?? [] }],
    deliveryGate: {
      schemaVersion: 'wisdom-weasel.delivery-gate-observation.v1', gateReceiptId: `gate-${rootId}`, rootId,
      catalogRevisionId: catalogId, targetCommit: 'commit-current', mode: 'observe_warn', gateStatus: options.gateStatus ?? 'observed_pass',
      enforcementApplied: false, blindReviewStatus: options.reasons?.includes('blind_review_not_passed') ? 'failed' : 'passed',
      reasons: options.reasons ?? [], proofMatrix: [{ criterionId: 'criterion-a', criterionKind: 'user_journey', passed: true, receiptIds: [`receipt-${rootId}`] }], createdAtMs: 4,
    },
    conflicts: [{ conflictId: 'conflict-1', leftItemId: 'item-a', rightItemId: 'item-b', conflictKind: 'ambiguity', status: 'open', resolution: '' }],
    peerReviewRounds: [{ roundId: 'peer-round-1', reviewerActorRefs: ['peer-reviewer'], verdicts: ['pass'], status: 'passed', receiptRef: 'peer-receipt-1', conflictMatrixRevisionId: null }],
  };
}
