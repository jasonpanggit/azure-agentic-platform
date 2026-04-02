'use client';

import React from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { MetricCard } from './MetricCard';

interface IncidentThroughputPoint {
  hour: string;
  count: number;
}

interface IncidentThroughputCardProps {
  data: IncidentThroughputPoint[];
}

function formatHour(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return iso;
  }
}

export function IncidentThroughputCard({ data }: IncidentThroughputCardProps) {
  const total = data.reduce((sum, d) => sum + d.count, 0);

  if (data.length === 0) {
    return (
      <MetricCard title="Incident Throughput" health="healthy">
        <span className="text-sm text-muted-foreground">No incidents in period</span>
      </MetricCard>
    );
  }

  const chartData = data.map((d) => ({ ...d, hour: formatHour(d.hour) }));

  return (
    <MetricCard title="Incident Throughput" health="healthy">
      <div className="flex flex-col gap-1">
        <div className="flex items-baseline gap-1 mb-1">
          <span className="font-mono text-3xl font-semibold" style={{ color: 'var(--text-primary)' }}>
            {total}
          </span>
          <span className="text-xs text-muted-foreground">total in period</span>
        </div>
        <ResponsiveContainer width="100%" height={80}>
          <BarChart data={chartData} margin={{ top: 0, right: 4, left: -30, bottom: 0 }}>
            <XAxis
              dataKey="hour"
              tick={{ fontSize: 9 }}
              interval="preserveStartEnd"
            />
            <YAxis tick={{ fontSize: 9 }} allowDecimals={false} />
            <Tooltip
              formatter={(value: unknown) => [Number(value), 'Incidents']}
              contentStyle={{ fontSize: 11 }}
            />
            <Bar dataKey="count" fill="var(--accent-blue)" radius={[2, 2, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </MetricCard>
  );
}
