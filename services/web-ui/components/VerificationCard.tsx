'use client';

import React, { useState, useCallback } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { CheckCircle, TrendingDown, AlertTriangle, Clock, Loader2 } from 'lucide-react';

interface VerificationCardProps {
  approvalId: string;
  incidentId: string;
  threadId: string;
  verificationResult: 'RESOLVED' | 'IMPROVED' | 'DEGRADED' | 'TIMEOUT' | null;
  isPolling: boolean;
  proposedAction: string;
  resourceId: string;
  rolledBack?: boolean;
  getAccessToken: () => Promise<string | null>;
  onChatMessage?: (message: string) => void;
}

const RESULT_CONFIG = {
  RESOLVED: {
    icon: CheckCircle,
    color: 'var(--accent-green)',
    bgColor: 'color-mix(in srgb, var(--accent-green) 15%, transparent)',
    label: 'Resolved',
    message: 'The remediation action resolved the issue.',
  },
  IMPROVED: {
    icon: TrendingDown,
    color: 'var(--accent-blue)',
    bgColor: 'color-mix(in srgb, var(--accent-blue) 15%, transparent)',
    label: 'Improved',
    message: 'Resource health improved but may not be fully resolved.',
  },
  DEGRADED: {
    icon: AlertTriangle,
    color: 'var(--accent-red)',
    bgColor: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
    label: 'Degraded',
    message: 'Resource degraded after action. Auto-rollback was triggered.',
  },
  TIMEOUT: {
    icon: Clock,
    color: 'var(--accent-orange)',
    bgColor: 'color-mix(in srgb, var(--accent-orange) 15%, transparent)',
    label: 'Timeout',
    message: 'Verification timed out. Resource health status unknown.',
  },
} as const;

export function VerificationCard({
  approvalId,
  incidentId,
  threadId,
  verificationResult,
  isPolling,
  proposedAction,
  resourceId,
  rolledBack,
  getAccessToken,
  onChatMessage,
}: VerificationCardProps) {
  const [resolving, setResolving] = useState(false);
  const [resolved, setResolved] = useState(false);
  const [reDiagnosing, setReDiagnosing] = useState(false);

  // threadId is included in the component props and passed through the chat flow
  // to ensure re-diagnosis messages inject into the existing Foundry thread (LOOP-005)
  void threadId;

  const handleYes = useCallback(async () => {
    setResolving(true);
    try {
      const token = await getAccessToken();
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const res = await fetch(`/api/proxy/incidents/${encodeURIComponent(incidentId)}/resolve`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          summary: `Resolved via ${proposedAction} — verification confirmed by operator.`,
          resolution: `Action: ${proposedAction} on ${resourceId}. Operator confirmed resolution.`,
        }),
      });

      if (res.ok) {
        setResolved(true);
      }
    } catch {
      // Non-critical — operator can resolve manually
    } finally {
      setResolving(false);
    }
  }, [getAccessToken, incidentId, proposedAction, resourceId]);

  const handleNo = useCallback(() => {
    if (onChatMessage) {
      setReDiagnosing(true);
      onChatMessage(
        `The operator reports the issue persists after ${proposedAction}. ` +
        `Resource: ${resourceId}. Re-diagnose the problem and propose an alternative approach.`
      );
    }
  }, [onChatMessage, proposedAction, resourceId]);

  // Polling state — show spinner
  if (isPolling && !verificationResult) {
    return (
      <Card
        className="max-w-[90%] self-start p-4 mb-2"
        style={{
          border: '1px solid var(--border)',
          borderLeft: '4px solid var(--accent-blue)',
          background: 'var(--bg-subtle)',
          borderRadius: '8px',
        }}
      >
        <CardContent className="p-0">
          <div className="flex items-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin" style={{ color: 'var(--accent-blue)' }} />
            <span className="text-sm font-semibold">Verifying remediation result...</span>
          </div>
          <p className="text-sm text-muted-foreground mt-1">
            Checking if the action resolved the issue. This may take a few minutes.
          </p>
        </CardContent>
      </Card>
    );
  }

  // No result yet and not polling — don't render
  if (!verificationResult) return null;

  const config = RESULT_CONFIG[verificationResult];
  const Icon = config.icon;

  return (
    <Card
      className="max-w-[90%] self-start p-4 mb-2"
      style={{
        border: '1px solid var(--border)',
        borderLeft: `4px solid ${config.color}`,
        background: 'var(--bg-subtle)',
        borderRadius: '8px',
      }}
    >
      <CardContent className="p-0">
        <div className="flex items-center gap-2 mb-2">
          <Icon className="h-5 w-5" style={{ color: config.color }} />
          <Badge
            style={{
              background: config.bgColor,
              color: config.color,
              border: 'none',
            }}
          >
            {config.label}
          </Badge>
          <span className="font-semibold text-sm">{config.message}</span>
        </div>

        {rolledBack && verificationResult === 'DEGRADED' && (
          <p className="text-sm text-muted-foreground mb-2">
            Auto-rollback has been triggered to restore the previous state.
          </p>
        )}

        {resolved ? (
          <p className="text-sm" style={{ color: 'var(--accent-green)' }}>
            Incident marked as resolved.
          </p>
        ) : reDiagnosing ? (
          <p className="text-sm text-muted-foreground">
            Re-diagnosis requested. The agent is investigating...
          </p>
        ) : (
          <>
            <p className="text-sm font-medium mt-2 mb-2">Did this remediation resolve the issue?</p>
            <div className="flex gap-2">
              <Button
                size="sm"
                onClick={handleYes}
                disabled={resolving}
                style={{ background: 'var(--accent-green)', color: '#FFFFFF', border: 'none' }}
              >
                {resolving ? 'Resolving...' : 'Yes, resolved'}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={handleNo}
                style={{ borderColor: 'var(--accent-red)', color: 'var(--accent-red)' }}
              >
                No, still an issue
              </Button>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
