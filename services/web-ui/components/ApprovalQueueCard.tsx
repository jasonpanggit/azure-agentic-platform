'use client';

import React from 'react';
import { MetricCard, HealthStatus } from './MetricCard';

interface ApprovalQueueData {
  pending: number;
  oldestPendingMinutes: number | null;
}

function getQueueHealth(pending: number): HealthStatus {
  if (pending > 25) return 'critical';
  if (pending > 10) return 'warning';
  return 'healthy';
}

interface ApprovalQueueCardProps {
  data: ApprovalQueueData;
}

export function ApprovalQueueCard({ data }: ApprovalQueueCardProps) {
  const health = getQueueHealth(data.pending);

  return (
    <MetricCard title="Approval Queue" health={health}>
      <div className="flex flex-col gap-1">
        <div className="flex justify-between items-center py-1">
          <span className="text-sm text-muted-foreground">Pending</span>
          <span className="text-2xl font-semibold">{data.pending}</span>
        </div>
        <div className="flex justify-between items-center py-1">
          <span className="text-sm text-muted-foreground">Oldest pending</span>
          <span className="font-mono text-[13px]">
            {data.oldestPendingMinutes !== null ? `${data.oldestPendingMinutes}m ago` : 'n/a'}
          </span>
        </div>
      </div>
    </MetricCard>
  );
}
