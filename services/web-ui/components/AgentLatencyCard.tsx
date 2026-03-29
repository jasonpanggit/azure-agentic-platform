'use client';

import React from 'react';
import { MetricCard, HealthStatus } from './MetricCard';

interface AgentLatencyRow {
  agent: string;
  p50: number;
  p95: number;
}

function getP95Health(p95: number): HealthStatus {
  if (p95 > 5000) return 'critical';
  if (p95 > 3000) return 'warning';
  return 'healthy';
}

interface AgentLatencyCardProps {
  data: AgentLatencyRow[];
}

export function AgentLatencyCard({ data }: AgentLatencyCardProps) {
  const worstHealth = data.reduce<HealthStatus>(
    (worst, row) => {
      const h = getP95Health(row.p95);
      if (h === 'critical') return 'critical';
      if (h === 'warning' && worst !== 'critical') return 'warning';
      return worst;
    },
    'healthy'
  );

  return (
    <MetricCard title="Agent Latency" health={worstHealth}>
      <div className="flex flex-col gap-1">
        {data.map((row) => (
          <div key={row.agent} className="flex justify-between items-center py-1">
            <span className="text-sm">{row.agent}</span>
            <div className="flex gap-4">
              <div className="flex flex-col items-end">
                <span className="text-xs text-muted-foreground">P50</span>
                <span className="font-mono text-[13px]">{row.p50}ms</span>
              </div>
              <div className="flex flex-col items-end">
                <span className="text-xs text-muted-foreground">P95</span>
                <span className="font-mono text-[13px]">{row.p95}ms</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </MetricCard>
  );
}
