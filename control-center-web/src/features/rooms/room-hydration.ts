export type RoomRecoveryState = 'recovering' | 'failed' | 'synced' | undefined;

export type RoomHydrationState =
  | 'loading'
  | 'ready-empty'
  | 'ready-content'
  | 'failed-empty'
  | 'failed-with-cache';

/** Keep a failed snapshot distinct from a Room confirmed to have no posts. */
export function roomHydrationState({
  hasContent,
  loading,
  recoveryState,
}: {
  hasContent: boolean;
  loading: boolean;
  recoveryState: RoomRecoveryState;
}): RoomHydrationState {
  if (recoveryState === 'failed') {
    return hasContent ? 'failed-with-cache' : 'failed-empty';
  }
  if (loading || recoveryState === 'recovering') return 'loading';
  return hasContent ? 'ready-content' : 'ready-empty';
}
