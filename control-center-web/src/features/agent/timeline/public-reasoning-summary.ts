/** Normalize only Runtime-authorized public reasoning summaries, including stored receipts. */
export function publicReasoningSummaryText(value: string): string {
  return value.replace(/<\/?thinking\s*>/giu, '').replace(/\s+/gu, ' ').trim();
}
