'use client';

import React from 'react';
import { MetricCard } from './MetricCard';

interface ActiveError {
  timestamp: string;
  agent: string;
  error: string;
  detail: string;
}

interface ActiveErrorsCardProps {
  data: ActiveError[];
}

export function ActiveErrorsCard({ data }: ActiveErrorsCardProps) {
  const health = data.length > 0 ? 'critical' as const : 'healthy' as const;

  return (
    <MetricCard title="Active Errors" health={health}>
      {data.length === 0 ? (
        <div className="py-4 text-center">
          <span className="text-sm text-muted-foreground">No active errors</span>
        </div>
      ) : (
        <div className="flex flex-col gap-1">
          {data.map((err, idx) => (
            <div key={idx} className="flex flex-col gap-0.5 py-1 border-b last:border-0">
              <div className="flex items-center gap-2">
                <span className="font-mono text-[13px]">{err.agent}</span>
                <span className="text-sm">{err.error}</span>
              </div>
              <span className="text-xs text-muted-foreground">
                {new Date(err.timestamp).toLocaleTimeString()}
              </span>
            </div>
          ))}
        </div>
      )}
    </MetricCard>
  );
}
