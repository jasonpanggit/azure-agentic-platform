'use client';

import React from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';

type HealthStatus = 'healthy' | 'warning' | 'critical';

interface MetricCardProps {
  title: string;
  health: HealthStatus;
  children: React.ReactNode;
}

const badgeLabelMap: Record<HealthStatus, string> = {
  healthy: 'Healthy',
  warning: 'Warning',
  critical: 'Critical',
};

const accentColorMap: Record<HealthStatus, string> = {
  healthy: 'var(--accent-green)',
  warning: 'var(--accent-yellow)',
  critical: 'var(--accent-red)',
};

export function MetricCard({ title, health, children }: MetricCardProps) {
  return (
    <Card
      className="p-4 hover:shadow-md transition-shadow"
      style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border)',
        borderLeft: `3px solid ${accentColorMap[health]}`,
        borderRadius: '8px',
      }}
    >
      <CardContent className="p-0">
        <div className="flex justify-between items-center mb-2">
          <span
            className="text-xs"
            style={{ color: 'var(--text-muted)' }}
          >
            {title}
          </span>
          <Badge
            variant={health === 'critical' ? 'destructive' : health === 'warning' ? 'outline' : 'default'}
          >
            {badgeLabelMap[health]}
          </Badge>
        </div>
        <div
          className="font-mono text-2xl font-semibold"
          style={{ color: 'var(--text-primary)' }}
        >
          {children}
        </div>
      </CardContent>
    </Card>
  );
}

export type { HealthStatus };
