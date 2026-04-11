'use client';

import { useState, useEffect, useRef, useCallback } from 'react';

interface VerificationResult {
  execution_id: string;
  approval_id: string;
  verification_result: 'RESOLVED' | 'IMPROVED' | 'DEGRADED' | 'TIMEOUT' | null;
  verified_at: string | null;
  resource_id?: string;
  proposed_action?: string;
  rolled_back?: boolean;
  status?: string;
}

interface UseVerificationPollOptions {
  approvalId: string | null;
  executedAt: string | null;
  delayMinutes?: number;
  maxAttempts?: number;
  pollIntervalMs?: number;
  getAccessToken: () => Promise<string | null>;
}

interface UseVerificationPollReturn {
  result: VerificationResult | null;
  isPolling: boolean;
  error: string | null;
}

/**
 * Custom hook that polls the verification endpoint after a remediation execution.
 *
 * Starts polling `delayMinutes` after `executedAt` timestamp. Polls every
 * `pollIntervalMs` (default 30s) for up to `maxAttempts` (default 20).
 * Stops when verification_result is non-null or max attempts reached.
 */
export function useVerificationPoll({
  approvalId,
  executedAt,
  delayMinutes = 5,
  maxAttempts = 20,
  pollIntervalMs = 30000,
  getAccessToken,
}: UseVerificationPollOptions): UseVerificationPollReturn {
  const [result, setResult] = useState<VerificationResult | null>(null);
  const [isPolling, setIsPolling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const attemptRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const poll = useCallback(async () => {
    if (!approvalId) return;

    attemptRef.current += 1;
    if (attemptRef.current > maxAttempts) {
      setIsPolling(false);
      setError('Verification polling timed out after max attempts');
      if (intervalRef.current) clearInterval(intervalRef.current);
      return;
    }

    try {
      const token = await getAccessToken();
      const headers: Record<string, string> = {};
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const res = await fetch(
        `/api/proxy/approvals/${encodeURIComponent(approvalId)}/verification`,
        { method: 'GET', headers }
      );

      if (res.status === 202) {
        // Still pending — continue polling
        return;
      }

      if (res.status === 404) {
        // No execution record yet — continue polling
        return;
      }

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data?.error || `Verification check failed: ${res.status}`);
        return;
      }

      const data: VerificationResult = await res.json();
      if (data.verification_result !== null && data.verification_result !== undefined) {
        setResult(data);
        setIsPolling(false);
        if (intervalRef.current) clearInterval(intervalRef.current);
      }
    } catch (err) {
      // Transient error — continue polling
      console.warn('Verification poll failed:', err);
    }
  }, [approvalId, maxAttempts, getAccessToken]);

  useEffect(() => {
    if (!approvalId || !executedAt) return;

    // Calculate delay before first poll
    const executedTime = new Date(executedAt).getTime();
    const pollStartTime = executedTime + delayMinutes * 60 * 1000;
    const now = Date.now();
    const delayMs = Math.max(pollStartTime - now, 0);

    attemptRef.current = 0;
    setResult(null);
    setError(null);

    // Start polling after delay
    timerRef.current = setTimeout(() => {
      setIsPolling(true);
      poll(); // First poll immediately
      intervalRef.current = setInterval(poll, pollIntervalMs);
    }, delayMs);

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      if (intervalRef.current) clearInterval(intervalRef.current);
      setIsPolling(false);
    };
  }, [approvalId, executedAt, delayMinutes, pollIntervalMs, poll]);

  return { result, isPolling, error };
}
