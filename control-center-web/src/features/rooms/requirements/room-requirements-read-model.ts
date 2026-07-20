import type { DeliveryGateObservationV1 } from '@/contracts/generated/delivery-gate-observation.v1';
import type { RequirementAnchorV1 } from '@/contracts/generated/requirement-anchor.v1';
import type { RequirementCatalogRevisionV1 } from '@/contracts/generated/requirement-catalog-revision.v1';
import type { TypedVerificationReceiptV1 } from '@/contracts/generated/typed-verification-receipt.v1';
import { parseContract } from '@/contracts/validators';

export type RequirementAnchorReadProjection = {
  anchor: RequirementAnchorV1;
  originalText: string;
  integrityStatus: 'verified' | 'tampered';
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
  reviewerActorRefs: string[];
  verdicts: ('pass' | 'fail' | 'abstain')[];
  status: 'pending' | 'passed' | 'failed' | 'conflict';
  receiptRef: string | null;
  conflictMatrixRevisionId: string | null;
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
  receiptAssessments: ReceiptAssessment[];
  deliveryGate: DeliveryGateObservationV1 | null;
  conflicts: RequirementConflictReadProjection[];
  peerReviewRounds: PeerReviewRoundReadProjection[];
};

export type ReceiptAssessment = {
  receipt: TypedVerificationReceiptV1;
  status: 'observed_pass' | 'failed' | 'stale' | 'tampered';
  reasons: string[];
};

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
    return { anchor, originalText: requiredString(raw.originalText, 'originalText'), integrityStatus: oneOf(raw.integrityStatus, ['verified', 'tampered'] as const, 'integrityStatus') };
  });
  const catalog = item.catalog === null || item.catalog === undefined
    ? null
    : parseContract('requirement-catalog-revision.v1', item.catalog);
  if (catalog && catalog.rootId !== rootId) throw new TypeError('RequirementCatalog belongs to another Root');
  if (catalog && catalog.anchorRefs.some((ref) => !anchors.some(({ anchor }) => anchor.anchorId === ref))) {
    throw new TypeError('RequirementCatalog references an anchor missing from the read projection');
  }
  const receiptAssessments = array(item.receiptAssessments).map((entry) => {
    const raw = record(entry);
    return {
      receipt: parseContract('typed-verification-receipt.v1', raw.receipt),
      status: oneOf(raw.status, ['observed_pass', 'failed', 'stale', 'tampered'] as const, 'proof status'),
      reasons: stringArray(raw.reasons),
    };
  });
  const deliveryGate = item.deliveryGate === null || item.deliveryGate === undefined
    ? null
    : parseContract('delivery-gate-observation.v1', item.deliveryGate);
  if (deliveryGate && deliveryGate.rootId !== rootId) throw new TypeError('DeliveryGate belongs to another Root');
  return {
    projectionSource,
    rootId,
    anchors,
    catalog,
    receiptAssessments,
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
    reviewerActorRefs: stringArray(item.reviewerActorRefs),
    verdicts: array(item.verdicts).map((value) => oneOf(value, ['pass', 'fail', 'abstain'] as const, 'peer verdict')),
    status: oneOf(item.status, ['pending', 'passed', 'failed', 'conflict'] as const, 'review status'),
    receiptRef: item.receiptRef === null ? null : requiredString(item.receiptRef, 'receiptRef'),
    conflictMatrixRevisionId: item.conflictMatrixRevisionId === null ? null : requiredString(item.conflictMatrixRevisionId, 'conflictMatrixRevisionId'),
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
function stringArray(value: unknown): string[] { return array(value).filter((item): item is string => typeof item === 'string'); }
function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
