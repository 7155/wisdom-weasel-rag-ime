export interface OffsetPosition {
    readonly start?: {
        readonly offset?: number;
    };
    readonly end?: {
        readonly offset?: number;
    };
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
export declare const ROOT_CHILDREN_SNAPSHOT_KEY = "progressiveRootChildren";
/** Snapshot root children before transforms that may replace nodes. */
export declare function rememberRootChildren(root: PositionedNode, file: ProcessorFileLike): void;
/**
 * Restore source positions onto newly inserted root elements by pairing them
 * with transformed-away source nodes. Position data is later used to split one
 * finalized whole-document tree back across stable streaming chunks.
 */
export declare function restoreInsertedRootPositions(root: PositionedNode, file: ProcessorFileLike): void;
/**
 * Distribute finalized root children into chunks according to absolute source
 * offsets. Unpositioned element nodes use the next positioned sibling as a
 * conservative tie-breaker.
 */
export declare function splitPositionedChildrenByOffsets<T extends PositionedNode>(children: readonly T[], chunkOffsets: readonly number[]): readonly (readonly T[])[];
//# sourceMappingURL=positionedTree.d.ts.map