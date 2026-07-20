import type { DeliveryGateObservationV1 } from '@/contracts/generated/delivery-gate-observation.v1';
import type { RequirementAnchorV1 } from '@/contracts/generated/requirement-anchor.v1';
import type { RequirementCatalogRevisionV1 } from '@/contracts/generated/requirement-catalog-revision.v1';
import type { TypedVerificationReceiptV1 } from '@/contracts/generated/typed-verification-receipt.v1';
import { parseContract } from '@/contracts/validators';

export type RequirementAnchorReadProjection = {
  anchor: RequirementAnchorV1;
  originalText: string;
};

export type RequirementConflictReadProjection = {
  conflictId: string;
  leftItemId: string;
  rightItemId: string;
  conflictKind: 'contradiction' | 'unknown' | 'ambiguity';
  status: 'open' | 'resolved';
  resolution: string;
};

export type PeerReviewRoundReadProjection = {
  roundId: string;
  reviewerActorRef: string;
  status: 'pending' | 'passed' | 'failed' | 'unavailable';
  receiptRef: string | null;
};

/**
 * A read-only composition of canonical artifacts. The UI may display this data,
 * but must not manufacture conflicts, reviews, proof, or delivery decisions.
 */
export type RoomRequirementsReadProjection = {
  projectionSource: 'canonical_read_projection' | 'canonical_fixture';
  rootId: string;
  anchors: RequirementAnchorReadProjection[];
  catalog: RequirementCatalogRevisionV1 | null;
  receipts: TypedVerificationReceiptV1[];
  deliveryGate: DeliveryGateObservationV1 | null;
  conflicts: RequirementConflictReadProjection[];
  peerReviewRounds: PeerReviewRoundReadProjection[];
};

export type ReceiptAssessment = {
  receipt: TypedVerificationReceiptV1;
  status: 'observed_pass' | 'failed' | 'stale' | 'tampered';
  reasons: string[];
};

const TRUSTED_VERIFIERS: Record<TypedVerificationReceiptV1['receiptType'], string> = {
  test: 'managed-test-runner',
  build: 'managed-build-runner',
  install: 'managed-install-verifier',
  evidence: 'managed-evidence-verifier',
};

export function assessReceipt(
  receipt: TypedVerificationReceiptV1,
  projection: RoomRequirementsReadProjection,
): ReceiptAssessment {
  const reasons: string[] = [];
  const catalogId = projection.catalog?.catalogRevisionId;
  const targetCommit = projection.deliveryGate?.targetCommit;
  if (receipt.rootId !== projection.rootId) reasons.push('cross_root');
  if (!catalogId || receipt.catalogRevisionId !== catalogId) reasons.push('old_catalog_revision');
  if (projection.deliveryGate && projection.deliveryGate.catalogRevisionId !== catalogId) reasons.push('old_catalog_revision');
  if (receipt.verifier !== TRUSTED_VERIFIERS[receipt.receiptType]) reasons.push('untrusted_verifier');
  if (!/^[0-9a-f]{64}$/.test(receipt.outputHash) || !/^[0-9a-f]{64}$/.test(receipt.artifactHash)) {
    reasons.push('invalid_hash');
  }
  if (targetCommit && receipt.sourceCommit !== targetCommit) reasons.push('wrong_commit');
  if (reasons.some((reason) => ['cross_root', 'untrusted_verifier', 'invalid_hash'].includes(reason))) {
    return { receipt, status: 'tampered', reasons };
  }
  if (reasons.length) return { receipt, status: 'stale', reasons: [...new Set(reasons)] };
  if (receipt.exitStatus !== 0) return { receipt, status: 'failed', reasons: ['non_zero_exit'] };
  return { receipt, status: 'observed_pass', reasons: [] };
}

export async function verifyOriginalAnchor(
  projection: RequirementAnchorReadProjection,
): Promise<'verified' | 'tampered'> {
  const bytes = new TextEncoder().encode(projection.originalText);
  if (bytes.byteLength !== projection.anchor.originalByteLength) return 'tampered';
  const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes);
  const actual = Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, '0')).join('');
  return actual === projection.anchor.originalContentSha256 ? 'verified' : 'tampered';
}

export function parseRoomRequirementsReadProjection(value: unknown): RoomRequirementsReadProjection {
  const item = record(value);
  const rootId = requiredString(item.rootId, 'rootId');
  const projectionSource = item.projectionSource;
  if (projectionSource !== 'canonical_read_projection' && projectionSource !== 'canonical_fixture') {
    throw new TypeError('Requirements projection must identify a canonical read source');
  }
  const anchors = array(item.anchors).map((entry) => {
    const raw = record(entry);
    const anchor = parseContract('requirement-anchor.v1', raw.anchor);
    if (anchor.rootId !== rootId) throw new TypeError('RequirementAnchor belongs to another Root');
    return { anchor, originalText: requiredString(raw.originalText, 'originalText') };
  });
  const catalog = item.catalog === null || item.catalog === undefined
    ? null
    : parseContract('requirement-catalog-revision.v1', item.catalog);
  if (catalog && catalog.rootId !== rootId) throw new TypeError('RequirementCatalog belongs to another Root');
  if (catalog && catalog.anchorRefs.some((ref) => !anchors.some(({ anchor }) => anchor.anchorId === ref))) {
    throw new TypeError('RequirementCatalog references an anchor missing from the read projection');
  }
  const receipts = array(item.receipts).map((entry) => parseContract('typed-verification-receipt.v1', entry));
  const deliveryGate = item.deliveryGate === null || item.deliveryGate === undefined
    ? null
    : parseContract('delivery-gate-observation.v1', item.deliveryGate);
  if (deliveryGate && deliveryGate.rootId !== rootId) throw new TypeError('DeliveryGate belongs to another Root');
  return {
    projectionSource,
    rootId,
    anchors,
    catalog,
    receipts,
    deliveryGate,
    conflicts: array(item.conflicts).map(parseConflict),
    peerReviewRounds: array(item.peerReviewRounds).map(parsePeerReviewRound),
  };
}

function parseConflict(value: unknown): RequirementConflictReadProjection {
  const item = record(value);
  const conflictKind = oneOf(item.conflictKind, ['contradiction', 'unknown', 'ambiguity'] as const, 'conflictKind');
  const status = oneOf(item.status, ['open', 'resolved'] as const, 'conflict status');
  return {
    conflictId: requiredString(item.conflictId, 'conflictId'),
    leftItemId: requiredString(item.leftItemId, 'leftItemId'),
    rightItemId: requiredString(item.rightItemId, 'rightItemId'),
    conflictKind,
    status,
    resolution: typeof item.resolution === 'string' ? item.resolution : '',
  };
}

function parsePeerReviewRound(value: unknown): PeerReviewRoundReadProjection {
  const item = record(value);
  return {
    roundId: requiredString(item.roundId, 'roundId'),
    reviewerActorRef: requiredString(item.reviewerActorRef, 'reviewerActorRef'),
    status: oneOf(item.status, ['pending', 'passed', 'failed', 'unavailable'] as const, 'review status'),
    receiptRef: item.receiptRef === null ? null : requiredString(item.receiptRef, 'receiptRef'),
  };
}

function requiredString(value: unknown, name: string): string {
  if (typeof value !== 'string' || !value.trim()) throw new TypeError(`${name} is required`);
  return value;
}

function oneOf<const Values extends readonly string[]>(value: unknown, values: Values, name: string): Values[number] {
  if (typeof value !== 'string' || !values.includes(value)) throw new TypeError(`${name} is invalid`);
  return value as Values[number];
}

function array(value: unknown): unknown[] { return Array.isArray(value) ? value : []; }
function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
