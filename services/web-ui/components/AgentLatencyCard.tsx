'use client';

import React from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';
import { MetricCard, HealthStatus } from './MetricCard';

interface AgentLatencyRow {
  agent: string;
  p50: number;
  p95: number;
}

interface AgentLatencyCardProps {
  data: AgentLatencyRow[];
}

function getP95Health(p95: number): HealthStatus {
  if (p95 > 5000) return 'critical';
  if (p95 > 3000) return 'warning';
  return 'healthy';
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

  if (data.length === 0) {
    return (
      <MetricCard title="Agent Latency" health="healthy">
        <span className="text-sm text-muted-foreground">No data</span>
      </MetricCard>
    );
  }

  return (
    <MetricCard title="Agent Latency" health={worstHealth}>
      <ResponsiveContainer width="100%" height={140}>
        <BarChart data={data} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
          <XAxis
            dataKey="agent"
            tick={{ fontSize: 10 }}
            tickFormatter={(v: string) =>
              v.length > 8 ? v.slice(0, 8) + '\u2026' : v
            }
          />
          <YAxis tick={{ fontSize: 10 }} unit="ms" />
          <Tooltip
            formatter={(value: unknown, name: unknown) => [
              `${Number(value)}ms`,
              String(name).toUpperCase(),
            ]}
            contentStyle={{ fontSize: 11 }}
          />
          <Legend iconSize={8} wrapperStyle={{ fontSize: 10 }} />
          <Bar
            dataKey="p50"
            name="P50"
            fill="var(--accent-blue)"
            radius={[2, 2, 0, 0]}
          />
          <Bar
            dataKey="p95"
            name="P95"
            fill="var(--accent-yellow)"
            radius={[2, 2, 0, 0]}
          />
        </BarChart>
      </ResponsiveContainer>
    </MetricCard>
  );
}
