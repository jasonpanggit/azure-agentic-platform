import { formatRelativeTime } from '../format-relative-time';

describe('formatRelativeTime', () => {
  let realDateNow: () => number;

  beforeEach(() => {
    realDateNow = Date.now;
  });

  afterEach(() => {
    Date.now = realDateNow;
  });

  function setNow(isoStr: string) {
    const t = new Date(isoStr).getTime();
    Date.now = () => t;
  }

  it('returns "just now" for timestamps less than 1 minute ago', () => {
    setNow('2024-01-01T12:00:00Z');
    expect(formatRelativeTime('2024-01-01T11:59:30Z')).toBe('just now');
    expect(formatRelativeTime('2024-01-01T12:00:00Z')).toBe('just now');
  });

  it('returns minutes ago for timestamps 1-59 minutes ago', () => {
    setNow('2024-01-01T12:00:00Z');
    expect(formatRelativeTime('2024-01-01T11:59:00Z')).toBe('1m ago');
    expect(formatRelativeTime('2024-01-01T11:30:00Z')).toBe('30m ago');
    expect(formatRelativeTime('2024-01-01T11:01:00Z')).toBe('59m ago');
  });

  it('returns hours ago for timestamps 1-23 hours ago', () => {
    setNow('2024-01-02T12:00:00Z');
    expect(formatRelativeTime('2024-01-02T11:00:00Z')).toBe('1h ago');
    expect(formatRelativeTime('2024-01-02T06:00:00Z')).toBe('6h ago');
    expect(formatRelativeTime('2024-01-01T13:00:00Z')).toBe('23h ago');
  });

  it('returns days ago for timestamps 24+ hours ago', () => {
    setNow('2024-01-10T12:00:00Z');
    expect(formatRelativeTime('2024-01-09T12:00:00Z')).toBe('1d ago');
    expect(formatRelativeTime('2024-01-05T12:00:00Z')).toBe('5d ago');
    expect(formatRelativeTime('2024-01-01T12:00:00Z')).toBe('9d ago');
  });

  it('returns the original string for invalid dates', () => {
    expect(formatRelativeTime('not-a-date')).toBe('not-a-date');
    expect(formatRelativeTime('')).toBe('');
    expect(formatRelativeTime('invalid')).toBe('invalid');
  });
});
