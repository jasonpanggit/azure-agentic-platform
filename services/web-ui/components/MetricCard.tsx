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

const borderColorMap: Record<HealthStatus, string> = {
  healthy: 'border-l-green-500',
  warning: 'border-l-yellow-500',
  critical: 'border-l-red-500',
};

const badgeLabelMap: Record<HealthStatus, string> = {
  healthy: 'Healthy',
  warning: 'Warning',
  critical: 'Critical',
};

export function MetricCard({ title, health, children }: MetricCardProps) {
  return (
    <Card className={`rounded-lg border-l-[3px] shadow-sm bg-card p-4 hover:shadow-md transition-shadow ${borderColorMap[health]}`}>
      <CardContent className="p-0">
        <div className="flex justify-between items-center mb-2">
          <span className="font-semibold text-base">{title}</span>
          <Badge
            variant={health === 'critical' ? 'destructive' : health === 'warning' ? 'outline' : 'default'}
          >
            {badgeLabelMap[health]}
          </Badge>
        </div>
        {children}
      </CardContent>
    </Card>
  );
}

export type { HealthStatus };
