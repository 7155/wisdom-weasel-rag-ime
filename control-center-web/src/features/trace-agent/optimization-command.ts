const pendingIds = new Map<string, string>();
const PREFIX = 'paw:trace-optimization-command:';

/** Keep uncertain action identity across retries, navigation and a tab refresh. */
export function traceOptimizationCommandId(key: string): string {
  let persisted = '';
  try { persisted = sessionStorage.getItem(PREFIX + key) || ''; } catch { /* Storage may be unavailable in an embedded host. */ }
  const id = persisted || pendingIds.get(key) || `trace-optimization:${crypto.randomUUID()}`;
  pendingIds.set(key, id);
  try { sessionStorage.setItem(PREFIX + key, id); } catch { /* The in-memory identity still protects retries. */ }
  return id;
}

export function settleTraceOptimizationCommand(key: string): void {
  pendingIds.delete(key);
  try { sessionStorage.removeItem(PREFIX + key); } catch { /* Nothing else to reconcile locally. */ }
}
