'use client';

import React, { useEffect, useState, useCallback } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { TrendingDown, RefreshCw, DollarSign } from 'lucide-react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CostRecommendation {
  resource_name: string;
  resource_type: string;
  resource_group: string;
  resource_id: string;
  current_sku: string;
  target_sku: string;
  estimated_monthly_savings: number;
  annual_savings: number;
  savings_currency: string;
  impact: 'High' | 'Medium' | 'Low';
  description: string;
  last_updated: string;
}

interface CostSummaryResponse {
  subscription_id: string;
  total_recommendations: number;
  recommendations?: CostRecommendation[];
  vms?: CostRecommendation[];  // deprecated alias — backend sends both
  error?: string;
  data_lag_note?: string;
}

interface CostTabProps {
  subscriptions: string[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function impactBadgeStyle(impact: string): React.CSSProperties {
  switch (impact) {
    case 'High':
      return { background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)', color: 'var(--accent-red)' };
    case 'Medium':
      return { background: 'color-mix(in srgb, var(--accent-orange) 15%, transparent)', color: 'var(--accent-orange)' };
    default:
      return { background: 'color-mix(in srgb, var(--accent-blue) 15%, transparent)', color: 'var(--accent-blue)' };
  }
}

function formatCurrency(amount: number, currency: string): string {
  return `${currency} ${amount.toFixed(2)}`;
}

/** Extract first sentence from description as a recommendation title. */
function extractTitle(description: string): string {
  if (!description) return 'Recommendation';
  // Split on period followed by space or end-of-string
  const firstSentence = description.split(/\.\s/)[0];
  if (firstSentence.length <= 80) {
    return firstSentence.endsWith('.') ? firstSentence : `${firstSentence}.`;
  }
  // Truncate at word boundary
  const truncated = firstSentence.slice(0, 80).replace(/\s+\S*$/, '');
  return `${truncated}...`;
}

/** Map resource type to a friendly display name. */
function cleanServiceType(resourceType: string): string {
  if (!resourceType) return 'Unknown';

  const lower = resourceType.toLowerCase();
  if (lower === 'subscriptions/subscriptions' || lower === 'microsoft.subscriptions/subscriptions') {
    return 'Subscription-level';
  }

  // Strip "Microsoft." prefix
  const stripped = resourceType.replace(/^Microsoft\./i, '');

  // Map common types to friendly names
  const friendlyNames: Record<string, string> = {
    'Compute/virtualMachines': 'Virtual Machines',
    'Compute/disks': 'Managed Disks',
    'Storage/storageAccounts': 'Storage Accounts',
    'Sql/servers': 'SQL Servers',
    'Web/sites': 'App Services',
    'ContainerService/managedClusters': 'AKS Clusters',
    'Network/publicIPAddresses': 'Public IPs',
    'DBforPostgreSQL/flexibleServers': 'PostgreSQL Flexible Servers',
    'CognitiveServices/accounts': 'AI Services',
  };

  return friendlyNames[stripped] ?? stripped;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function CostTab({ subscriptions }: CostTabProps) {
  const [recommendations, setRecommendations] = useState<CostRecommendation[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dataLagNote, setDataLagNote] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const fetchCostData = useCallback(async () => {
    if (subscriptions.length === 0) {
      setRecommendations([]);
      return;
    }

    setLoading(true);
    setError(null);

    try {
      // Fetch for first selected subscription (expand to multi-sub in future)
      const subscriptionId = subscriptions[0];
      const res = await fetch(
        `/api/proxy/vms/cost-summary?subscription_id=${encodeURIComponent(subscriptionId)}&top=10`,
        { signal: AbortSignal.timeout(15000) }
      );

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.error ?? `HTTP ${res.status}`);
      }

      const data: CostSummaryResponse = await res.json();
      if (data.error) {
        throw new Error(data.error);
      }

      // Read from "recommendations" first, fall back to deprecated "vms" key
      setRecommendations(data.recommendations ?? data.vms ?? []);
      setDataLagNote(data.data_lag_note ?? null);
      setLastRefresh(new Date());
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      setError(`Failed to load cost data: ${message}`);
      setRecommendations([]);
    } finally {
      setLoading(false);
    }
  }, [subscriptions]);

  useEffect(() => {
    fetchCostData();
  }, [fetchCostData]);

  // ---------------------------------------------------------------------------
  // Render states
  // ---------------------------------------------------------------------------

  if (loading) {
    return (
      <div className="p-6 space-y-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      </div>
    );
  }

  if (subscriptions.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 gap-3" style={{ color: 'var(--text-secondary)' }}>
        <TrendingDown className="h-10 w-10 opacity-30" />
        <p className="text-sm">Select a subscription to view cost recommendations.</p>
      </div>
    );
  }

  if (recommendations.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 gap-3" style={{ color: 'var(--text-secondary)' }}>
        <DollarSign className="h-10 w-10 opacity-30" />
        <p className="text-sm">No cost recommendations found.</p>
        <p className="text-xs opacity-60">Azure Advisor refreshes recommendations every 24 hours.</p>
      </div>
    );
  }

  // Calculate total potential savings
  const totalMonthlySavings = recommendations.reduce((sum, r) => sum + r.estimated_monthly_savings, 0);
  const currency = recommendations[0]?.savings_currency ?? 'USD';

  // Sort by savings descending (immutable)
  const sortedRecommendations = [...recommendations].sort(
    (a, b) => b.estimated_monthly_savings - a.estimated_monthly_savings
  );

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3" style={{ borderBottom: '1px solid var(--border)' }}>
        <div className="flex items-center gap-2">
          <TrendingDown className="h-4 w-4" style={{ color: 'var(--accent-blue)' }} />
          <span className="text-[13px] font-medium" style={{ color: 'var(--text-primary)' }}>
            Top Cost Optimization Opportunities
          </span>
          <Badge variant="outline" className="text-[11px]">
            {recommendations.length} recommendations
          </Badge>
          <span
            className="text-[12px] px-2 py-0.5 rounded"
            style={{
              background: 'color-mix(in srgb, var(--accent-green) 15%, transparent)',
              color: 'var(--accent-green)',
              fontWeight: 600,
            }}
          >
            {formatCurrency(totalMonthlySavings, currency)}/mo potential
          </span>
        </div>
        <div className="flex items-center gap-2">
          {lastRefresh && (
            <span className="text-[11px]" style={{ color: 'var(--text-secondary)' }}>
              Last updated: {lastRefresh.toLocaleTimeString()}
            </span>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={fetchCostData}
            disabled={loading}
            className="h-7 px-2 gap-1 text-[12px]"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </Button>
        </div>
      </div>

      {/* Data lag note */}
      {dataLagNote && (
        <div
          className="px-4 py-2 text-[11px]"
          style={{ color: 'var(--text-secondary)', borderBottom: '1px solid var(--border)' }}
        >
          {dataLagNote}
        </div>
      )}

      {/* Card grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 p-4">
        {sortedRecommendations.map((rec) => (
          <Card key={rec.resource_id || rec.resource_name}>
            <CardContent className="p-4">
              {/* Top row: impact badge + monthly savings */}
              <div className="flex items-center justify-between mb-2">
                <span
                  className="text-[11px] px-2 py-0.5 rounded font-medium"
                  style={impactBadgeStyle(rec.impact)}
                >
                  {rec.impact}
                </span>
                <span
                  className="text-[16px] font-semibold"
                  style={{ color: 'var(--accent-green)' }}
                >
                  {rec.estimated_monthly_savings > 0
                    ? `${formatCurrency(rec.estimated_monthly_savings, rec.savings_currency)}/mo`
                    : '\u2014'}
                </span>
              </div>

              {/* Title (extracted from description) */}
              <p
                className="text-[14px] font-medium mb-2"
                style={{ color: 'var(--text-primary)' }}
              >
                {extractTitle(rec.description)}
              </p>

              {/* Service type badge */}
              <span
                className="inline-block text-[11px] px-2 py-0.5 rounded mb-2"
                style={{
                  background: 'color-mix(in srgb, var(--accent-blue) 15%, transparent)',
                  color: 'var(--accent-blue)',
                }}
              >
                {cleanServiceType(rec.resource_type)}
              </span>

              {/* Full description */}
              <p
                className="text-[12px] leading-relaxed mb-3"
                style={{ color: 'var(--text-secondary)' }}
              >
                {rec.description || '\u2014'}
              </p>

              {/* Bottom row: annual savings + last updated */}
              <div
                className="flex items-center justify-between pt-2"
                style={{ borderTop: '1px solid var(--border)' }}
              >
                <span className="text-[11px]" style={{ color: 'var(--text-secondary)' }}>
                  {rec.annual_savings > 0
                    ? `Annual: ${formatCurrency(rec.annual_savings, rec.savings_currency)}/yr`
                    : ''}
                </span>
                <span className="text-[11px]" style={{ color: 'var(--text-secondary)' }}>
                  {rec.last_updated
                    ? new Date(rec.last_updated).toLocaleDateString()
                    : ''}
                </span>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
