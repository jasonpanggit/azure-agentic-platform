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
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { MetricCard, HealthStatus } from './MetricCard';
import { InstalledPatchesPanel, PanelMachine } from './InstalledPatchesPanel';
import { ShieldCheck, RefreshCw, Search } from 'lucide-react';
import { formatRelativeTime } from '@/lib/format-relative-time';

// ---------------------------------------------------------------------------
// Types (per 13-UI-SPEC.md Data Flow section)
// ---------------------------------------------------------------------------

interface AssessmentMachine {
  id: string;
  machineName: string;
  resourceGroup: string;
  subscriptionId: string;
  osType: string;
  osVersion: string;
  hasAssessmentData: boolean;
  rebootPending: boolean;
  lastAssessment: string | null;
  criticalCount: number;
  securityCount: number;
  updateRollupCount: number;
  featurePackCount: number;
  servicePackCount: number;
  definitionCount: number;
  toolsCount: number;
  updatesCount: number;
  installedCount: number;
  lastInstalled: string | null;
}

interface Installation {
  id: string;
  resourceGroup: string;
  subscriptionId: string;
  startTime: string;
  status: string;
  rebootStatus: string;
  installedCount: number;
  failedCount: number;
  pendingCount: number;
  startedBy: string;
}

interface PatchTabProps {
  subscriptions: string[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type ComplianceState = 'Compliant' | 'NonCompliant' | 'Unknown';

function deriveCompliance(m: AssessmentMachine): ComplianceState {
  // Machines with no assessment data are always "Unknown"
  if (!m.hasAssessmentData) return 'Unknown';
  // Per UI-SPEC: criticalCount + securityCount === 0 and !rebootPending => Compliant
  // criticalCount > 0 or securityCount > 0 => NonCompliant; else Unknown
  if (m.criticalCount > 0 || m.securityCount > 0) return 'NonCompliant';
  if (m.criticalCount === 0 && m.securityCount === 0 && !m.rebootPending) return 'Compliant';
  return 'Unknown';
}

function extractMachineName(resourceId: string): string {
  // Extract machine name from resource ID — last segment before /patchAssessmentResults or /patchInstallationResults
  const parts = resourceId.split('/');
  // Find the machines or virtualMachines segment, then the next segment is the name
  for (let i = 0; i < parts.length; i++) {
    if (
      parts[i].toLowerCase() === 'virtualmachines' ||
      parts[i].toLowerCase() === 'machines'
    ) {
      return parts[i + 1] ?? resourceId;
    }
  }
  return parts[parts.length - 1] ?? resourceId;
}


function complianceHealth(compliantPct: number): HealthStatus {
  if (compliantPct >= 90) return 'healthy';
  if (compliantPct >= 70) return 'warning';
  return 'critical';
}

function countHealth(count: number, warnMax: number): HealthStatus {
  if (count === 0) return 'healthy';
  if (count <= warnMax) return 'warning';
  return 'critical';
}

// ---------------------------------------------------------------------------
// Badge sub-components
// ---------------------------------------------------------------------------

function ComplianceBadge({ state }: { state: ComplianceState }) {
  if (state === 'Compliant') {
    return (
      <Badge className="bg-green-100 text-green-700 border-green-200 border">
        Compliant
      </Badge>
    );
  }
  if (state === 'NonCompliant') {
    return (
      <Badge className="bg-red-100 text-red-700 border-red-200 border">
        NonCompliant
      </Badge>
    );
  }
  return <Badge variant="outline">Unknown</Badge>;
}

function InstallStatusBadge({ status }: { status: string }) {
  switch (status) {
    case 'Succeeded':
      return (
        <Badge className="bg-green-100 text-green-700 border-green-200 border">
          Succeeded
        </Badge>
      );
    case 'Failed':
      return <Badge variant="destructive">Failed</Badge>;
    case 'InProgress':
      return (
        <Badge className="bg-blue-100 text-blue-700 border-blue-200 border">
          InProgress
        </Badge>
      );
    case 'CompletedWithWarnings':
      return (
        <Badge className="bg-yellow-100 text-yellow-700 border-yellow-200 border">
          Warnings
        </Badge>
      );
    default:
      return <Badge variant="outline">{status || 'NotStarted'}</Badge>;
  }
}

// ---------------------------------------------------------------------------
// PatchTab Component
// ---------------------------------------------------------------------------

export function PatchTab({ subscriptions }: PatchTabProps) {
  const [assessmentData, setAssessmentData] = useState<AssessmentMachine[] | null>(null);
  const [installationsData, setInstallationsData] = useState<Installation[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [complianceFilter, setComplianceFilter] = useState('all');
  const [machineSearch, setMachineSearch] = useState('');
  const [selectedMachine, setSelectedMachine] = useState<PanelMachine | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);

  const handleRowClick = useCallback((m: AssessmentMachine) => {
    const panel: PanelMachine = {
      id: m.id,
      machineName: m.machineName,
      resourceGroup: m.resourceGroup,
      osType: m.osType,
      osVersion: m.osVersion,
      rebootPending: m.rebootPending,
      criticalCount: m.criticalCount,
      securityCount: m.securityCount,
      installedCount: m.installedCount,
    };
    setSelectedMachine(panel);
    setPanelOpen(true);
  }, []);

  const handlePanelOpenChange = useCallback((open: boolean) => {
    setPanelOpen(open);
    if (!open) {
      setSelectedMachine(null);
    }
  }, []);

  const fetchData = useCallback(async () => {
    if (subscriptions.length === 0) {
      setAssessmentData(null);
      setInstallationsData(null);
      setLoading(false);
      setError(null);
      return;
    }

    setLoading(true);
    setError(null);

    const subsParam = subscriptions.join(',');

    try {
      const [assessmentRes, installationsRes] = await Promise.all([
        fetch(`/api/proxy/patch/assessment?subscriptions=${encodeURIComponent(subsParam)}`, {
          signal: AbortSignal.timeout(15000),
        }),
        fetch(`/api/proxy/patch/installations?subscriptions=${encodeURIComponent(subsParam)}`, {
          signal: AbortSignal.timeout(15000),
        }),
      ]);

      let assessmentErr: string | null = null;
      let installationsErr: string | null = null;

      if (assessmentRes.ok) {
        const aData = await assessmentRes.json();
        setAssessmentData(aData.machines ?? []);
      } else {
        const aErr = await assessmentRes.json().catch(() => ({}));
        assessmentErr = aErr.error ?? `Assessment query failed (${assessmentRes.status})`;
        setAssessmentData(null);
      }

      if (installationsRes.ok) {
        const iData = await installationsRes.json();
        setInstallationsData(iData.installations ?? []);
      } else {
        const iErr = await installationsRes.json().catch(() => ({}));
        installationsErr = iErr.error ?? `Installations query failed (${installationsRes.status})`;
        setInstallationsData(null);
      }

      // Set error if either failed
      if (assessmentErr && installationsErr) {
        setError('Unable to load patch data. Check that the API gateway is running and the selected subscriptions have Azure Update Manager enabled.');
      } else if (assessmentErr) {
        setError(assessmentErr);
      } else if (installationsErr) {
        setError(installationsErr);
      }
    } catch (err) {
      setError(
        'Unable to load patch data. Check that the API gateway is running and the selected subscriptions have Azure Update Manager enabled.'
      );
    } finally {
      setLoading(false);
    }
  }, [subscriptions]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // ---------------------------------------------------------------------------
  // Derived data
  // ---------------------------------------------------------------------------

  const assessmentWithCompliance = (assessmentData ?? []).map((m) => ({
    ...m,
    compliance: deriveCompliance(m),
  }));

  const filteredAssessment = assessmentWithCompliance.filter((m) => {
    const matchesCompliance =
      complianceFilter === 'all' || m.compliance === complianceFilter;
    const q = machineSearch.toLowerCase();
    const matchesSearch = q === '' || m.machineName.toLowerCase().includes(q);
    return matchesCompliance && matchesSearch;
  });

  // Summary stats
  const totalMachines = assessmentWithCompliance.length;
  const compliantCount = assessmentWithCompliance.filter(
    (m) => m.compliance === 'Compliant'
  ).length;
  const compliantPct = totalMachines > 0 ? Math.round((compliantCount / totalMachines) * 100) : 0;
  const criticalSecurityTotal = assessmentWithCompliance.reduce(
    (sum, m) => sum + (m.criticalCount ?? 0) + (m.securityCount ?? 0),
    0
  );
  const rebootPendingCount = assessmentWithCompliance.filter(
    (m) => m.rebootPending
  ).length;
  const failedInstallsCount = (installationsData ?? []).filter(
    (i) => i.status !== 'Succeeded'
  ).length;

  // ---------------------------------------------------------------------------
  // Empty state (no subscriptions)
  // ---------------------------------------------------------------------------

  if (subscriptions.length === 0 && !loading) {
    return (
      <div className="flex flex-col items-center justify-center py-16 gap-3">
        <ShieldCheck className="h-8 w-8 text-muted-foreground" />
        <p className="font-semibold text-base text-foreground">No patch data available</p>
        <p className="text-sm text-muted-foreground text-center max-w-[360px]">
          Patch assessment data will appear here once Azure Update Manager runs on your
          selected subscriptions. Select one or more subscriptions above.
        </p>
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="flex flex-col gap-6 p-4">
      {/* Section 1 — Header row */}
      <div className="flex justify-between items-center">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
            Patch Management
          </span>
          {!loading && assessmentData !== null && (
            <span className="text-xs text-muted-foreground" aria-live="polite">
              {totalMachines} machine{totalMachines !== 1 ? 's' : ''}
            </span>
          )}
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={fetchData}
          disabled={loading}
        >
          <RefreshCw className={`h-4 w-4 mr-1 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {/* Error state */}
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* Section 2 — Summary cards */}
      {loading && !assessmentData ? (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-[88px] rounded-lg" />
          ))}
        </div>
      ) : assessmentData !== null ? (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
          <MetricCard title="Total Machines" health="healthy">
            {totalMachines}
          </MetricCard>
          <MetricCard title="Compliant" health={complianceHealth(compliantPct)}>
            {compliantPct}%
          </MetricCard>
          <MetricCard title="Critical + Security" health={countHealth(criticalSecurityTotal, 10)}>
            {criticalSecurityTotal}
          </MetricCard>
          <MetricCard title="Reboot Pending" health={countHealth(rebootPendingCount, 3)}>
            {rebootPendingCount}
          </MetricCard>
          <MetricCard
            title="Failed Installs"
            health={installationsData !== null ? countHealth(failedInstallsCount, 3) : 'healthy'}
          >
            {installationsData !== null ? failedInstallsCount : '\u2014'}
          </MetricCard>
        </div>
      ) : null}

      {/* Section 3 — Assessment table */}
      {(assessmentData !== null || loading) && (
        <div className="flex flex-col gap-3">
          <span className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
            Patch Assessment
          </span>

          {/* Filter bar */}
          <div className="flex gap-2 items-center flex-wrap">
            <Select value={complianceFilter} onValueChange={setComplianceFilter}>
              <SelectTrigger className="w-[160px]">
                <SelectValue placeholder="All states" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All states</SelectItem>
                <SelectItem value="Compliant">Compliant</SelectItem>
                <SelectItem value="NonCompliant">NonCompliant</SelectItem>
                <SelectItem value="Unknown">Unknown</SelectItem>
              </SelectContent>
            </Select>

            <div className="relative flex-1 max-w-[280px]">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
              <Input
                className="pl-8"
                placeholder="Search machines..."
                value={machineSearch}
                onChange={(e) => setMachineSearch(e.target.value)}
              />
            </div>

            {!loading && assessmentData !== null && (
              <span className="text-xs text-muted-foreground" aria-live="polite">
                {filteredAssessment.length} of {totalMachines} machine
                {totalMachines !== 1 ? 's' : ''}
              </span>
            )}
          </div>

          {/* Loading skeleton */}
          {loading && !assessmentData && (
            <div className="flex flex-col gap-1">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          )}

          {/* Assessment table */}
          {!loading && assessmentData !== null && filteredAssessment.length === 0 && (
            <p className="text-sm text-muted-foreground text-center py-8">
              No machines match the current filters.
            </p>
          )}

          {assessmentData !== null && filteredAssessment.length > 0 && (
            <div className="rounded-md border overflow-hidden overflow-x-auto">
              <Table className="w-full min-w-[1200px] text-sm">
                <TableHeader>
                  <TableRow>
                    <TableHead className="h-10 px-3 text-left font-semibold text-muted-foreground min-w-[140px]">Machine</TableHead>
                    <TableHead className="h-10 px-3 text-left font-semibold text-muted-foreground w-[60px]">OS</TableHead>
                    <TableHead className="h-10 px-3 text-left font-semibold text-muted-foreground w-[120px]">Compliance</TableHead>
                    <TableHead className="h-10 px-3 text-right font-semibold text-muted-foreground w-[70px]">Critical</TableHead>
                    <TableHead className="h-10 px-3 text-right font-semibold text-muted-foreground w-[70px]">Security</TableHead>
                    <TableHead className="h-10 px-3 text-right font-semibold text-muted-foreground w-[70px]">Rollup</TableHead>
                    <TableHead className="h-10 px-3 text-right font-semibold text-muted-foreground w-[70px]">Feature</TableHead>
                    <TableHead className="h-10 px-3 text-right font-semibold text-muted-foreground w-[70px]">Service</TableHead>
                    <TableHead className="h-10 px-3 text-right font-semibold text-muted-foreground w-[70px]">Definition</TableHead>
                    <TableHead className="h-10 px-3 text-right font-semibold text-muted-foreground w-[70px]">Tools</TableHead>
                    <TableHead className="h-10 px-3 text-right font-semibold text-muted-foreground w-[70px]">Updates</TableHead>
                    <TableHead className="h-10 px-3 text-left font-semibold text-muted-foreground w-[120px]">Reboot</TableHead>
                    <TableHead className="h-10 px-3 text-left font-semibold text-muted-foreground min-w-[120px]">Last Assessed</TableHead>
                    <TableHead className="h-10 px-3 text-right font-semibold text-muted-foreground w-[80px]">Installed</TableHead>
                    <TableHead className="h-10 px-3 text-left font-semibold text-muted-foreground min-w-[120px]">Last Installed</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredAssessment.map((m) => (
                    <TableRow
                      key={m.id}
                      className="border-b hover:bg-muted/50 transition-colors cursor-pointer"
                      onClick={() => handleRowClick(m)}
                    >
                      <TableCell className="h-10 px-3 align-middle font-mono text-[13px] truncate max-w-[200px]">
                        {m.machineName}
                      </TableCell>
                      <TableCell className="h-10 px-3 align-middle">
                        <Badge variant="secondary" className="text-xs">
                          {m.osVersion || m.osType}
                        </Badge>
                      </TableCell>
                      <TableCell className="h-10 px-3 align-middle">
                        <ComplianceBadge state={m.compliance} />
                      </TableCell>
                      <TableCell className={`h-10 px-3 align-middle font-mono text-[13px] text-right ${m.criticalCount > 0 ? 'text-red-600' : ''}`}>
                        {m.criticalCount ?? 0}
                      </TableCell>
                      <TableCell className={`h-10 px-3 align-middle font-mono text-[13px] text-right ${m.securityCount > 0 ? 'text-red-600' : ''}`}>
                        {m.securityCount ?? 0}
                      </TableCell>
                      <TableCell className="h-10 px-3 align-middle font-mono text-[13px] text-right">
                        {m.updateRollupCount ?? 0}
                      </TableCell>
                      <TableCell className="h-10 px-3 align-middle font-mono text-[13px] text-right">
                        {m.featurePackCount ?? 0}
                      </TableCell>
                      <TableCell className="h-10 px-3 align-middle font-mono text-[13px] text-right">
                        {m.servicePackCount ?? 0}
                      </TableCell>
                      <TableCell className="h-10 px-3 align-middle font-mono text-[13px] text-right">
                        {m.definitionCount ?? 0}
                      </TableCell>
                      <TableCell className="h-10 px-3 align-middle font-mono text-[13px] text-right">
                        {m.toolsCount ?? 0}
                      </TableCell>
                      <TableCell className="h-10 px-3 align-middle font-mono text-[13px] text-right">
                        {m.updatesCount ?? 0}
                      </TableCell>
                      <TableCell className="h-10 px-3 align-middle">
                        {m.rebootPending ? (
                          <Badge className="bg-orange-100 text-orange-700 border-orange-200 border">
                            Reboot Required
                          </Badge>
                        ) : (
                          <span className="text-muted-foreground">&mdash;</span>
                        )}
                      </TableCell>
                      <TableCell className="h-10 px-3 align-middle text-[13px] text-muted-foreground">
                        {m.lastAssessment ? formatRelativeTime(m.lastAssessment) : '\u2014'}
                      </TableCell>
                      <TableCell className="h-10 px-3 align-middle font-mono text-[13px] text-right">
                        <span className={m.installedCount > 0 ? 'hover:underline text-blue-400' : ''}>
                          {m.installedCount > 0 ? m.installedCount : '\u2014'}
                        </span>
                      </TableCell>
                      <TableCell className="h-10 px-3 align-middle text-[13px] text-muted-foreground">
                        {m.lastInstalled ? formatRelativeTime(m.lastInstalled) : 'Never'}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </div>
      )}

      {/* Section 4 — Installation history table */}
      {(installationsData !== null || loading) && (
        <div className="flex flex-col gap-3">
          <span className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
            Installation History &mdash; Last 7 Days
          </span>

          {/* Loading skeleton */}
          {loading && !installationsData && (
            <div className="flex flex-col gap-1">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          )}

          {/* Empty state */}
          {!loading && installationsData !== null && installationsData.length === 0 && (
            <p className="text-sm text-muted-foreground text-center py-8">
              No installation runs recorded in the last 7 days.
            </p>
          )}

          {/* Installations table */}
          {installationsData !== null && installationsData.length > 0 && (
            <div className="rounded-md border overflow-hidden overflow-x-auto">
              <Table className="w-full text-sm">
                <TableHeader>
                  <TableRow>
                    <TableHead className="h-10 px-3 text-left font-semibold text-muted-foreground min-w-[140px]">Machine</TableHead>
                    <TableHead className="h-10 px-3 text-left font-semibold text-muted-foreground min-w-[100px]">Started</TableHead>
                    <TableHead className="h-10 px-3 text-left font-semibold text-muted-foreground w-[140px]">Status</TableHead>
                    <TableHead className="h-10 px-3 text-right font-semibold text-muted-foreground w-[80px]">Installed</TableHead>
                    <TableHead className="h-10 px-3 text-right font-semibold text-muted-foreground w-[80px]">Failed</TableHead>
                    <TableHead className="h-10 px-3 text-right font-semibold text-muted-foreground w-[80px]">Pending</TableHead>
                    <TableHead className="h-10 px-3 text-left font-semibold text-muted-foreground w-[100px]">Reboot</TableHead>
                    <TableHead className="h-10 px-3 text-left font-semibold text-muted-foreground min-w-[100px]">Started By</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {installationsData.map((inst) => (
                    <TableRow key={inst.id} className="border-b hover:bg-muted/30 transition-colors">
                      <TableCell className="h-10 px-3 align-middle font-mono text-[13px] truncate max-w-[200px]">
                        {extractMachineName(inst.id)}
                      </TableCell>
                      <TableCell className="h-10 px-3 align-middle text-[13px] text-muted-foreground">
                        {inst.startTime ? formatRelativeTime(inst.startTime) : '\u2014'}
                      </TableCell>
                      <TableCell className="h-10 px-3 align-middle">
                        <InstallStatusBadge status={inst.status} />
                      </TableCell>
                      <TableCell className="h-10 px-3 align-middle font-mono text-[13px] text-right">
                        {inst.installedCount ?? 0}
                      </TableCell>
                      <TableCell className={`h-10 px-3 align-middle font-mono text-[13px] text-right ${(inst.failedCount ?? 0) > 0 ? 'text-red-600' : ''}`}>
                        {inst.failedCount ?? 0}
                      </TableCell>
                      <TableCell className="h-10 px-3 align-middle font-mono text-[13px] text-right">
                        {inst.pendingCount ?? 0}
                      </TableCell>
                      <TableCell className="h-10 px-3 align-middle">
                        <Badge variant="outline" className="text-xs">
                          {inst.rebootStatus || 'NotNeeded'}
                        </Badge>
                      </TableCell>
                      <TableCell className="h-10 px-3 align-middle text-[13px] text-muted-foreground truncate max-w-[160px]">
                        {inst.startedBy || '\u2014'}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </div>
      )}
      {/* Drill-down panel for installed patches */}
      <InstalledPatchesPanel
        machine={selectedMachine}
        open={panelOpen}
        onOpenChange={handlePanelOpenChange}
      />
    </div>
  );
}
