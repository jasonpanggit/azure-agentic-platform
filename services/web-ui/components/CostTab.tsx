'use client';

import React, { useEffect, useState, useCallback } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { TrendingDown, RefreshCw, DollarSign } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';

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

// FinOps-specific types
interface CostBreakdownItem {
  name: string;
  cost: number;
  currency: string;
}

interface CostBreakdownResponse {
  subscription_id: string;
  total_cost: number;
  currency: string;
  breakdown: CostBreakdownItem[];
  data_lag_note?: string;
  query_status: string;
}

interface CostForecastResponse {
  subscription_id: string;
  current_spend_usd: number;
  forecast_month_end_usd: number;
  budget_amount_usd: number | null;
  burn_rate_pct: number | null;
  days_elapsed: number;
  days_in_month: number;
  over_budget: boolean;
  over_budget_pct: number;
  data_lag_note?: string;
  query_status: string;
}

interface IdleResource {
  resource_id: string;
  vm_name: string;
  resource_group: string;
  avg_cpu_pct: number;
  avg_network_mbps: number;
  monthly_cost_usd: number;
  approval_id?: string | null;
}

interface IdleResourcesResponse {
  subscription_id: string;
  vms_evaluated: number;
  idle_count: number;
  idle_resources: IdleResource[];
  query_status: string;
}

interface RiUtilisationResponse {
  subscription_id: string;
  method: string;
  actual_cost_usd: number;
  amortized_cost_usd: number;
  ri_benefit_estimated_usd: number;
  utilisation_note: string;
  data_lag_note?: string;
  query_status: string;
}

interface TopCostDriver {
  service_name: string;
  cost_usd: number;
  currency: string;
  rank: number;
}

interface TopCostDriversResponse {
  subscription_id: string;
  n: number;
  days: number;
  drivers: TopCostDriver[];
  total_cost_usd: number;
  data_lag_note?: string;
  query_status: string;
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

  // FinOps state
  const [breakdown, setBreakdown] = useState<CostBreakdownItem[]>([]);
  const [forecast, setForecast] = useState<CostForecastResponse | null>(null);
  const [idleResources, setIdleResources] = useState<IdleResource[]>([]);
  const [riUtilisation, setRiUtilisation] = useState<RiUtilisationResponse | null>(null);
  const [finopsLoading, setFinopsLoading] = useState(false);
  const [finopsError, setFinopsError] = useState<string | null>(null);
  const [approvingId, setApprovingId] = useState<string | null>(null);

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

  const fetchFinopsData = useCallback(async () => {
    if (subscriptions.length === 0) return;
    setFinopsLoading(true);
    setFinopsError(null);
    const subscriptionId = subscriptions[0];

    try {
      // Parallel fetch all 4 FinOps endpoints
      const [breakdownRes, forecastRes, idleRes, riRes] = await Promise.allSettled([
        fetch(`/api/proxy/finops/cost-breakdown?subscription_id=${encodeURIComponent(subscriptionId)}&days=30&group_by=ResourceGroup`, { signal: AbortSignal.timeout(15000) }),
        fetch(`/api/proxy/finops/cost-forecast?subscription_id=${encodeURIComponent(subscriptionId)}`, { signal: AbortSignal.timeout(15000) }),
        fetch(`/api/proxy/finops/idle-resources?subscription_id=${encodeURIComponent(subscriptionId)}`, { signal: AbortSignal.timeout(15000) }),
        fetch(`/api/proxy/finops/ri-utilization?subscription_id=${encodeURIComponent(subscriptionId)}`, { signal: AbortSignal.timeout(15000) }),
      ]);

      if (breakdownRes.status === 'fulfilled' && breakdownRes.value.ok) {
        const d: CostBreakdownResponse = await breakdownRes.value.json();
        setBreakdown(d.breakdown?.slice(0, 10) ?? []);
      }
      if (forecastRes.status === 'fulfilled' && forecastRes.value.ok) {
        const d: CostForecastResponse = await forecastRes.value.json();
        setForecast(d);
      }
      if (idleRes.status === 'fulfilled' && idleRes.value.ok) {
        const d: IdleResourcesResponse = await idleRes.value.json();
        setIdleResources(d.idle_resources ?? []);
      }
      if (riRes.status === 'fulfilled' && riRes.value.ok) {
        const d: RiUtilisationResponse = await riRes.value.json();
        setRiUtilisation(d);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      setFinopsError(`Failed to load FinOps data: ${message}`);
    } finally {
      setFinopsLoading(false);
    }
  }, [subscriptions]);

  useEffect(() => {
    fetchCostData();
    fetchFinopsData();
  }, [fetchCostData, fetchFinopsData]);

  // ---------------------------------------------------------------------------
  // HITL handlers
  // ---------------------------------------------------------------------------

  const handleApprove = async (approvalId: string) => {
    setApprovingId(approvalId);
    try {
      await fetch(`/api/proxy/approvals/${encodeURIComponent(approvalId)}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ notes: 'Approved via FinOps tab' }),
        signal: AbortSignal.timeout(10000),
      });
      // Refresh idle resources after approval
      await fetchFinopsData();
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      setFinopsError(`Approval failed: ${message}`);
    } finally {
      setApprovingId(null);
    }
  };

  const handleReject = async (approvalId: string) => {
    setApprovingId(approvalId);
    try {
      await fetch(`/api/proxy/approvals/${encodeURIComponent(approvalId)}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ notes: 'Rejected via FinOps tab' }),
        signal: AbortSignal.timeout(10000),
      });
      await fetchFinopsData();
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      setFinopsError(`Rejection failed: ${message}`);
    } finally {
      setApprovingId(null);
    }
  };

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

  if (recommendations.length === 0 && !finopsLoading && !forecast && breakdown.length === 0 && idleResources.length === 0) {
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
            onClick={() => { fetchCostData(); fetchFinopsData(); }}
            disabled={loading || finopsLoading}
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

      {/* FinOps error banner */}
      {finopsError && (
        <div className="px-4 pt-3">
          <Alert variant="destructive">
            <AlertDescription>{finopsError}</AlertDescription>
          </Alert>
        </div>
      )}

      {/* FinOps loading skeletons */}
      {finopsLoading && (
        <div className="px-4 pt-4 space-y-2">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
      )}

      {/* ───── FinOps KPIs ───── */}
      {!finopsLoading && forecast && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 px-4 pt-4">
          {/* Current month spend */}
          <Card>
            <CardContent className="p-3">
              <p className="text-[11px] mb-1" style={{ color: 'var(--text-secondary)' }}>Month-to-Date Spend</p>
              <p className="text-[20px] font-semibold" style={{ color: 'var(--text-primary)' }}>
                ${forecast.current_spend_usd != null ? forecast.current_spend_usd.toFixed(0) : '—'}
              </p>
              <p className="text-[11px]" style={{ color: 'var(--text-secondary)' }}>
                Day {forecast.days_elapsed} of {forecast.days_in_month}
              </p>
            </CardContent>
          </Card>
          {/* Forecast */}
          <Card>
            <CardContent className="p-3">
              <p className="text-[11px] mb-1" style={{ color: 'var(--text-secondary)' }}>Forecast Month-End</p>
              <p className="text-[20px] font-semibold" style={{ color: forecast.over_budget ? 'var(--accent-red)' : 'var(--text-primary)' }}>
                ${forecast.forecast_month_end_usd != null ? forecast.forecast_month_end_usd.toFixed(0) : '—'}
              </p>
              {forecast.over_budget && (
                <span className="text-[11px]" style={{ color: 'var(--accent-red)' }}>
                  ⚠ {forecast.over_budget_pct != null ? forecast.over_budget_pct.toFixed(0) : '?'}% over budget
                </span>
              )}
            </CardContent>
          </Card>
          {/* Budget gauge */}
          {forecast.budget_amount_usd != null && (
            <Card className="col-span-2">
              <CardContent className="p-3">
                <p className="text-[11px] mb-2" style={{ color: 'var(--text-secondary)' }}>
                  Budget: ${forecast.budget_amount_usd.toFixed(0)}
                </p>
                {(() => {
                  const burnPct = Math.min(((forecast.forecast_month_end_usd / forecast.budget_amount_usd!) * 100), 150);
                  const barColor = burnPct > 110 ? 'var(--accent-red)' : burnPct > 90 ? 'var(--accent-orange)' : 'var(--accent-green)';
                  return (
                    <>
                      <div className="relative h-3 rounded-full" style={{ background: 'color-mix(in srgb, var(--border) 50%, transparent)' }}>
                        <div
                          className="absolute inset-y-0 left-0 rounded-full transition-all"
                          style={{ width: `${Math.min(burnPct, 100)}%`, background: barColor }}
                        />
                      </div>
                      <p className="text-[11px] mt-1" style={{ color: 'var(--text-secondary)' }}>
                        Projected {burnPct.toFixed(0)}% of budget
                        {burnPct > 110 && <span style={{ color: 'var(--accent-red)' }}> — on track to exceed by {(burnPct - 100).toFixed(0)}%</span>}
                      </p>
                    </>
                  );
                })()}
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {/* ───── Cost Breakdown Chart ───── */}
      {!finopsLoading && breakdown.length > 0 && (
        <div className="px-4 pt-4">
          <p className="text-[13px] font-medium mb-2" style={{ color: 'var(--text-primary)' }}>
            Top Resource Groups by Spend (30d)
          </p>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart
              data={breakdown.map(b => ({
                name: b.name.length > 18 ? b.name.slice(0, 18) + '…' : b.name,
                cost: b.cost,
              }))}
              layout="vertical"
              margin={{ top: 4, right: 50, left: 10, bottom: 0 }}
            >
              <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={(v: number) => `$${v.toFixed(0)}`} />
              <YAxis type="category" dataKey="name" tick={{ fontSize: 10 }} width={120} />
              <Tooltip
                formatter={(v: unknown) => [`$${Number(v).toFixed(2)}`, 'Cost']}
                contentStyle={{ fontSize: 11 }}
              />
              <Bar dataKey="cost" fill="var(--accent-blue)" radius={[0, 2, 2, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* ───── Idle Resources (Waste List) ───── */}
      {!finopsLoading && idleResources.length > 0 && (
        <div className="px-4 pt-4">
          <div className="flex items-center gap-2 mb-2">
            <p className="text-[13px] font-medium" style={{ color: 'var(--text-primary)' }}>
              Idle Resources
            </p>
            <span
              className="text-[11px] px-2 py-0.5 rounded"
              style={{ background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)', color: 'var(--accent-red)' }}
            >
              {idleResources.length} VMs idle 72h+
            </span>
          </div>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-[11px]">VM Name</TableHead>
                <TableHead className="text-[11px]">Resource Group</TableHead>
                <TableHead className="text-[11px]">Avg CPU</TableHead>
                <TableHead className="text-[11px]">Monthly Cost</TableHead>
                <TableHead className="text-[11px]">Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {idleResources.map((r) => (
                <TableRow key={r.resource_id}>
                  <TableCell className="text-[12px]">{r.vm_name}</TableCell>
                  <TableCell className="text-[12px]" style={{ color: 'var(--text-secondary)' }}>{r.resource_group}</TableCell>
                  <TableCell className="text-[12px]">
                    <span style={{ color: 'var(--accent-orange)' }}>{r.avg_cpu_pct != null ? r.avg_cpu_pct.toFixed(1) : '—'}%</span>
                  </TableCell>
                  <TableCell className="text-[12px] font-medium" style={{ color: 'var(--accent-green)' }}>
                    ${r.monthly_cost_usd != null ? r.monthly_cost_usd.toFixed(0) : '—'}/mo
                  </TableCell>
                  <TableCell>
                    {r.approval_id ? (
                      <div className="flex gap-1">
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-6 px-2 text-[11px]"
                          style={{ color: 'var(--accent-green)', borderColor: 'var(--accent-green)' }}
                          disabled={approvingId === r.approval_id}
                          onClick={() => r.approval_id && handleApprove(r.approval_id)}
                        >
                          {approvingId === r.approval_id ? '…' : 'Approve'}
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-6 px-2 text-[11px]"
                          style={{ color: 'var(--text-secondary)' }}
                          disabled={approvingId === r.approval_id}
                          onClick={() => r.approval_id && handleReject(r.approval_id)}
                        >
                          Reject
                        </Button>
                      </div>
                    ) : (
                      <span className="text-[11px]" style={{ color: 'var(--text-secondary)' }}>No proposal</span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* ───── RI Utilisation ───── */}
      {!finopsLoading && riUtilisation && riUtilisation.query_status === 'success' && (
        <div className="px-4 pt-4">
          <Card>
            <CardContent className="p-4">
              <p className="text-[13px] font-medium mb-2" style={{ color: 'var(--text-primary)' }}>
                Reserved Instance Utilisation (30d)
              </p>
              <div className="flex items-center gap-4">
                <div>
                  <p className="text-[11px]" style={{ color: 'var(--text-secondary)' }}>RI Benefit Consumed</p>
                  <p className="text-[18px] font-semibold" style={{ color: riUtilisation.ri_benefit_estimated_usd > 0 ? 'var(--accent-green)' : 'var(--text-secondary)' }}>
                    ${Math.abs(riUtilisation.ri_benefit_estimated_usd).toFixed(0)}
                  </p>
                </div>
                <div className="flex-1">
                  <p className="text-[11px]" style={{ color: 'var(--text-secondary)' }}>{riUtilisation.utilisation_note}</p>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* ───── Divider before existing Advisor recommendations ───── */}
      {(breakdown.length > 0 || idleResources.length > 0 || forecast) && (
        <div className="px-4 pt-4 pb-2">
          <p className="text-[13px] font-medium" style={{ color: 'var(--text-primary)' }}>
            Azure Advisor Cost Recommendations
          </p>
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
