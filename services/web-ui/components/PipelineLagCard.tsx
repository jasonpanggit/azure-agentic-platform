'use client';

import React from 'react';
import { MetricCard, HealthStatus } from './MetricCard';

interface PipelineLagData {
  alertToIncidentMs: number;
  incidentToTriageMs: number;
  totalE2EMs: number;
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function getLagHealth(totalMs: number): HealthStatus {
  if (totalMs > 120000) return 'critical';
  if (totalMs > 60000) return 'warning';
  return 'healthy';
}

interface PipelineLagCardProps {
  data: PipelineLagData;
}

export function PipelineLagCard({ data }: PipelineLagCardProps) {
  const health = getLagHealth(data.totalE2EMs);

  const rows = [
    { label: 'Alert to Incident', value: data.alertToIncidentMs },
    { label: 'Incident to Triage', value: data.incidentToTriageMs },
    { label: 'Total End-to-End', value: data.totalE2EMs },
  ];

  return (
    <MetricCard title="Pipeline Lag" health={health}>
      <div className="flex flex-col gap-1">
        {rows.map((row) => (
          <div key={row.label} className="flex justify-between items-center py-1">
            <span className="text-sm text-muted-foreground">{row.label}</span>
            <span className="font-mono text-[13px]">{formatDuration(row.value)}</span>
          </div>
        ))}
      </div>
    </MetricCard>
  );
}
