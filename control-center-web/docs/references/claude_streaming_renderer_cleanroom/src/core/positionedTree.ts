export interface OffsetPosition {
  readonly start?: { readonly offset?: number };
  readonly end?: { readonly offset?: number };
}

export interface PositionedNode {
  readonly type: string;
  position?: OffsetPosition;
  children?: PositionedNode[];
  [key: string]: unknown;
}

export interface ProcessorFileLike {
  data: Record<string, unknown>;
}

export const ROOT_CHILDREN_SNAPSHOT_KEY = "progressiveRootChildren";

/** Snapshot root children before transforms that may replace nodes. */
export function rememberRootChildren(
  root: PositionedNode,
  file: ProcessorFileLike,
): void {
  file.data[ROOT_CHILDREN_SNAPSHOT_KEY] = root.children?.slice() ?? [];
}

/**
 * Restore source positions onto newly inserted root elements by pairing them
 * with transformed-away source nodes. Position data is later used to split one
 * finalized whole-document tree back across stable streaming chunks.
 */
export function restoreInsertedRootPositions(
  root: PositionedNode,
  file: ProcessorFileLike,
): void {
  const original = file.data[ROOT_CHILDREN_SNAPSHOT_KEY];
  delete file.data[ROOT_CHILDREN_SNAPSHOT_KEY];
  if (!Array.isArray(original) || original === root.children || !root.children) {
    return;
  }

  const originalNodes = original as PositionedNode[];
  const surviving = new Set(root.children);
  let originalCursor = 0;

  for (const node of root.children) {
    const originalIndex = originalNodes.indexOf(node, originalCursor);
    if (originalIndex >= 0) {
      originalCursor = originalIndex + 1;
      continue;
    }

    const candidate = originalNodes[originalCursor];
    if (
      node.type === "element" &&
      node.position === undefined &&
      candidate?.position !== undefined &&
      !surviving.has(candidate)
    ) {
      node.position = candidate.position;
    }
  }
}

/**
 * Distribute finalized root children into chunks according to absolute source
 * offsets. Unpositioned element nodes use the next positioned sibling as a
 * conservative tie-breaker.
 */
export function splitPositionedChildrenByOffsets<T extends PositionedNode>(
  children: readonly T[],
  chunkOffsets: readonly number[],
): readonly (readonly T[])[] {
  const buckets: T[][] = chunkOffsets.map(() => []);
  if (buckets.length === 0) return buckets;

  const nextPositionedOffset = Array.from(
    { length: children.length },
    () => Number.POSITIVE_INFINITY,
  );
  for (let index = children.length - 2; index >= 0; index -= 1) {
    const next = children[index + 1]?.position?.start?.offset;
    nextPositionedOffset[index] =
      typeof next === "number"
        ? next
        : (nextPositionedOffset[index + 1] ?? Number.POSITIVE_INFINITY);
  }

  let bucket = 0;
  children.forEach((node, index) => {
    const offset = node.position?.start?.offset;
    if (typeof offset === "number") {
      while (
        bucket + 1 < chunkOffsets.length &&
        offset >= (chunkOffsets[bucket + 1] ?? Number.POSITIVE_INFINITY)
      ) {
        bucket += 1;
      }
    } else if (
      node.type === "element" &&
      buckets[bucket]?.length &&
      bucket + 1 < chunkOffsets.length &&
      (chunkOffsets[bucket + 1] ?? Number.POSITIVE_INFINITY) <
        (nextPositionedOffset[index] ?? Number.POSITIVE_INFINITY)
    ) {
      bucket += 1;
    }
    buckets[bucket]?.push(node);
  });

  return buckets;
}
