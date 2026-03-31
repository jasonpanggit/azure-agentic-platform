/**
 * Formats an ISO 8601 timestamp as a human-readable relative time string.
 * Returns strings like "just now", "5m ago", "3h ago", "2d ago".
 * Returns the original string if the input is not a valid date.
 */
export function formatRelativeTime(isoStr: string): string {
  const now = Date.now();
  const then = new Date(isoStr).getTime();
  const diffMs = now - then;

  if (isNaN(then)) return isoStr;

  const minutes = Math.floor(diffMs / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;

  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;

  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}
