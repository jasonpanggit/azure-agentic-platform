'use client';

import React, { useEffect, useState, useCallback } from 'react';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { TrendingDown, RefreshCw, DollarSign } from 'lucide-react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CostVM {
  vm_name: string;
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
  vms: CostVM[];
  data_lag_note?: string;
  error?: string;
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

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function CostTab({ subscriptions }: CostTabProps) {
  const [vms, setVMs] = useState<CostVM[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dataLagNote, setDataLagNote] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const fetchCostData = useCallback(async () => {
    if (subscriptions.length === 0) {
      setVMs([]);
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

      setVMs(data.vms ?? []);
      setDataLagNote(data.data_lag_note ?? null);
      setLastRefresh(new Date());
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      setError(`Failed to load cost data: ${message}`);
      setVMs([]);
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

  if (vms.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 gap-3" style={{ color: 'var(--text-secondary)' }}>
        <DollarSign className="h-10 w-10 opacity-30" />
        <p className="text-sm">No rightsizing recommendations found.</p>
        <p className="text-xs opacity-60">Azure Advisor refreshes recommendations every 24 hours.</p>
      </div>
    );
  }

  // Calculate total potential savings
  const totalMonthlySavings = vms.reduce((sum, vm) => sum + vm.estimated_monthly_savings, 0);
  const currency = vms[0]?.savings_currency ?? 'USD';

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3" style={{ borderBottom: '1px solid var(--border)' }}>
        <div className="flex items-center gap-2">
          <TrendingDown className="h-4 w-4" style={{ color: 'var(--accent-blue)' }} />
          <span className="text-[13px] font-medium" style={{ color: 'var(--text-primary)' }}>
            Top Rightsizing Opportunities
          </span>
          <Badge variant="outline" className="text-[11px]">
            {vms.length} VMs
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
          ⏱ {dataLagNote}
        </div>
      )}

      {/* Table */}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="text-[12px]">VM Name</TableHead>
            <TableHead className="text-[12px]">Resource Group</TableHead>
            <TableHead className="text-[12px]">Current SKU</TableHead>
            <TableHead className="text-[12px]">Recommended SKU</TableHead>
            <TableHead className="text-[12px]">Monthly Savings</TableHead>
            <TableHead className="text-[12px]">Impact</TableHead>
            <TableHead className="text-[12px]">Description</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {vms.map((vm) => (
            <TableRow key={vm.resource_id || vm.vm_name}>
              <TableCell className="text-[13px] font-medium" style={{ color: 'var(--text-primary)' }}>
                {vm.vm_name || '—'}
              </TableCell>
              <TableCell className="text-[12px]" style={{ color: 'var(--text-secondary)' }}>
                {vm.resource_group || '—'}
              </TableCell>
              <TableCell className="text-[12px] font-mono" style={{ color: 'var(--text-secondary)' }}>
                {vm.current_sku || '—'}
              </TableCell>
              <TableCell className="text-[12px] font-mono" style={{ color: 'var(--accent-blue)' }}>
                {vm.target_sku || '—'}
              </TableCell>
              <TableCell className="text-[12px] font-semibold" style={{ color: 'var(--accent-green)' }}>
                {vm.estimated_monthly_savings > 0
                  ? formatCurrency(vm.estimated_monthly_savings, vm.savings_currency)
                  : '—'}
              </TableCell>
              <TableCell>
                <span
                  className="text-[11px] px-2 py-0.5 rounded font-medium"
                  style={impactBadgeStyle(vm.impact)}
                >
                  {vm.impact}
                </span>
              </TableCell>
              <TableCell
                className="text-[12px] max-w-[250px] truncate"
                style={{ color: 'var(--text-secondary)' }}
                title={vm.description}
              >
                {vm.description || '—'}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
