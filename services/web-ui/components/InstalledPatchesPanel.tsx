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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Package, AlertTriangle, RefreshCw, X, ShieldAlert } from 'lucide-react';
import { formatRelativeTime } from '@/lib/format-relative-time';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Machine data passed from the assessment table row */
export interface PanelMachine {
  readonly id: string;
  readonly machineName: string;
  readonly resourceGroup: string;
  readonly osType: string;
  readonly osVersion: string;
  readonly vmType: 'Azure VM' | 'Arc VM';
  readonly rebootPending: boolean;
  readonly criticalCount: number;
  readonly securityCount: number;
  readonly installedCount: number;
}

interface InstalledPatch {
  readonly SoftwareName: string;
  readonly SoftwareType: string;
  readonly CurrentVersion: string;
  readonly Publisher: string;
  readonly Category: string;
  readonly InstalledDate: string;
  readonly cves: readonly string[];
}

interface PendingPatch {
  readonly patchName: string;
  readonly classifications: readonly string[];
  readonly rebootRequired: boolean;
  readonly kbid: string;
  readonly version: string;
  readonly publishedDateTime: string | null;
}

interface InstalledPatchesPanelProps {
  readonly machine: PanelMachine | null;
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type DaysOption = '30' | '90' | '180' | '365';
type ActiveTab = 'pending' | 'installed';

const DAYS_OPTIONS: readonly { readonly value: DaysOption; readonly label: string }[] = [
  { value: '30', label: '30 days' },
  { value: '90', label: '90 days' },
  { value: '180', label: '180 days' },
  { value: '365', label: '365 days' },
] as const;

function classificationBadgeStyle(cls: string): React.CSSProperties {
  const lower = cls.toLowerCase();
  if (lower === 'security') {
    return {
      background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
      color: 'var(--accent-red)',
      borderColor: 'color-mix(in srgb, var(--accent-red) 35%, transparent)',
    };
  }
  if (lower === 'critical') {
    return {
      background: 'color-mix(in srgb, var(--accent-orange) 15%, transparent)',
      color: 'var(--accent-orange)',
      borderColor: 'color-mix(in srgb, var(--accent-orange) 35%, transparent)',
    };
  }
  return {};
}

const MAX_VISIBLE_CVES = 3;

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatChip({ label, value, variant }: {
  readonly label: string;
  readonly value: string | number;
  readonly variant?: 'default' | 'warning' | 'danger';
}) {
  const v = variant ?? 'default';

  const bgStyle: Record<string, React.CSSProperties> = {
    default: { background: 'var(--bg-subtle)', borderColor: 'var(--border)' },
    warning: {
      background: 'color-mix(in srgb, var(--accent-orange) 12%, transparent)',
      borderColor: 'color-mix(in srgb, var(--accent-orange) 35%, transparent)',
    },
    danger: {
      background: 'color-mix(in srgb, var(--accent-red) 12%, transparent)',
      borderColor: 'color-mix(in srgb, var(--accent-red) 35%, transparent)',
    },
  };

  const textColor: Record<string, string> = {
    default: 'var(--text-primary)',
    warning: 'var(--accent-orange)',
    danger: 'var(--accent-red)',
  };

  return (
    <div className="flex flex-col items-center rounded-lg border px-4 py-2.5" style={bgStyle[v]}>
      <span className="font-mono text-lg font-semibold" style={{ color: textColor[v] }}>{value}</span>
      <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>{label}</span>
    </div>
  );
}

function CveBadges({ cves }: { readonly cves: readonly string[] }) {
  if (cves.length === 0) return <span style={{ color: 'var(--text-muted)' }}>&mdash;</span>;

  const visible = cves.slice(0, MAX_VISIBLE_CVES);
  const overflow = cves.length - MAX_VISIBLE_CVES;

  return (
    <div className="flex flex-wrap gap-1">
      {visible.map((cve) => (
        <Badge key={cve} variant="outline" className="text-[10px] font-mono px-1.5 py-0"
          style={{ color: 'var(--text-secondary)', borderColor: 'var(--border)' }}>
          {cve}
        </Badge>
      ))}
      {overflow > 0 && (
        <Badge variant="outline" className="text-[10px] font-mono px-1.5 py-0"
          style={{ color: 'var(--text-muted)', borderColor: 'var(--border)' }}>
          +{overflow} more
        </Badge>
      )}
    </div>
  );
}

function SkeletonRows({ cols }: { readonly cols: number }) {
  return (
    <>
      {Array.from({ length: 3 }).map((_, i) => (
        <TableRow key={i}>
          <TableCell colSpan={cols} className="px-3 py-2">
            <Skeleton className="h-6 w-full" />
          </TableCell>
        </TableRow>
      ))}
    </>
  );
}

function EmptyState({ message }: { readonly message?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 gap-3">
      <Package className="h-8 w-8" style={{ color: 'var(--text-muted)' }} />
      <p className="text-sm text-center max-w-[320px]" style={{ color: 'var(--text-secondary)' }}>
        {message ?? 'No patches found for this machine.'}
      </p>
    </div>
  );
}

function ErrorState({ message, onRetry }: { readonly message?: string; readonly onRetry: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 gap-3">
      <AlertTriangle className="h-8 w-8" style={{ color: 'var(--accent-red)' }} />
      <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
        {message ?? 'Failed to load patch detail.'}
      </p>
      <Button variant="outline" size="sm" onClick={onRetry}>
        <RefreshCw className="h-3.5 w-3.5 mr-1" />
        Try again
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Pending Patches Table
// ---------------------------------------------------------------------------

function PendingPatchesTable({
  patches,
  loading,
  error,
  onRetry,
}: {
  readonly patches: readonly PendingPatch[];
  readonly loading: boolean;
  readonly error: string | null;
  readonly onRetry: () => void;
}) {
  if (loading) {
    return (
      <Table className="w-full text-sm">
        <TableHeader>
          <TableRow>
            <TableHead className="h-8 px-3 text-left text-xs font-semibold" style={{ color: 'var(--text-muted)' }}>Patch Name</TableHead>
            <TableHead className="h-8 px-3 text-left text-xs font-semibold w-[110px]" style={{ color: 'var(--text-muted)' }}>Classification</TableHead>
            <TableHead className="h-8 px-3 text-left text-xs font-semibold w-[80px]" style={{ color: 'var(--text-muted)' }}>KB ID</TableHead>
            <TableHead className="h-8 px-3 text-left text-xs font-semibold w-[80px]" style={{ color: 'var(--text-muted)' }}>Reboot</TableHead>
            <TableHead className="h-8 px-3 text-left text-xs font-semibold w-[100px]" style={{ color: 'var(--text-muted)' }}>Published</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody><SkeletonRows cols={5} /></TableBody>
      </Table>
    );
  }

  if (error) return <ErrorState message={error} onRetry={onRetry} />;

  if (patches.length === 0) {
    return (
      <EmptyState message="No pending patches found. This machine is up to date." />
    );
  }

  return (
    <div className="rounded-md border overflow-hidden" style={{ borderColor: 'var(--border)' }}>
      <Table className="w-full text-sm">
        <TableHeader>
          <TableRow>
            <TableHead className="h-8 px-3 text-left text-xs font-semibold" style={{ color: 'var(--text-muted)' }}>Patch Name</TableHead>
            <TableHead className="h-8 px-3 text-left text-xs font-semibold w-[110px]" style={{ color: 'var(--text-muted)' }}>Classification</TableHead>
            <TableHead className="h-8 px-3 text-left text-xs font-semibold w-[80px]" style={{ color: 'var(--text-muted)' }}>KB ID</TableHead>
            <TableHead className="h-8 px-3 text-left text-xs font-semibold w-[80px]" style={{ color: 'var(--text-muted)' }}>Reboot</TableHead>
            <TableHead className="h-8 px-3 text-left text-xs font-semibold w-[100px]" style={{ color: 'var(--text-muted)' }}>Published</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {patches.map((p, idx) => (
            <TableRow key={`${p.patchName}-${idx}`} className="border-b hover:bg-muted/50 transition-colors">
              <TableCell className="h-9 px-3 align-middle text-[13px] max-w-[240px] truncate" style={{ color: 'var(--text-primary)' }}>
                {p.patchName}
              </TableCell>
              <TableCell className="h-9 px-3 align-middle">
                <div className="flex flex-wrap gap-1">
                  {p.classifications.length > 0 ? p.classifications.map((cls) => (
                    <Badge key={cls} variant="outline" className="text-[11px] border" style={classificationBadgeStyle(cls)}>
                      {cls}
                    </Badge>
                  )) : (
                    <Badge variant="outline" className="text-[11px]">Other</Badge>
                  )}
                </div>
              </TableCell>
              <TableCell className="h-9 px-3 align-middle font-mono text-[12px]" style={{ color: 'var(--text-secondary)' }}>
                {p.kbid ? `KB${p.kbid}` : '\u2014'}
              </TableCell>
              <TableCell className="h-9 px-3 align-middle">
                {p.rebootRequired ? (
                  <Badge className="border text-[11px]" style={{
                    background: 'color-mix(in srgb, var(--accent-orange) 15%, transparent)',
                    color: 'var(--accent-orange)',
                    borderColor: 'color-mix(in srgb, var(--accent-orange) 35%, transparent)',
                  }}>
                    Required
                  </Badge>
                ) : (
                  <span className="text-[12px]" style={{ color: 'var(--text-muted)' }}>No</span>
                )}
              </TableCell>
              <TableCell className="h-9 px-3 align-middle text-[12px]" style={{ color: 'var(--text-secondary)' }}>
                {p.publishedDateTime ? formatRelativeTime(p.publishedDateTime) : '\u2014'}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Installed Patches Table
// ---------------------------------------------------------------------------

function InstalledPatchesTable({
  patches,
  loading,
  error,
  onRetry,
}: {
  readonly patches: readonly InstalledPatch[];
  readonly loading: boolean;
  readonly error: string | null;
  readonly onRetry: () => void;
}) {
  if (loading) {
    return (
      <Table className="w-full text-sm">
        <TableHeader>
          <TableRow>
            <TableHead className="h-8 px-3 text-left text-xs font-semibold" style={{ color: 'var(--text-muted)' }}>Name</TableHead>
            <TableHead className="h-8 px-3 text-left text-xs font-semibold w-[100px]" style={{ color: 'var(--text-muted)' }}>Version</TableHead>
            <TableHead className="h-8 px-3 text-left text-xs font-semibold w-[100px]" style={{ color: 'var(--text-muted)' }}>Category</TableHead>
            <TableHead className="h-8 px-3 text-left text-xs font-semibold w-[100px]" style={{ color: 'var(--text-muted)' }}>Publisher</TableHead>
            <TableHead className="h-8 px-3 text-left text-xs font-semibold w-[90px]" style={{ color: 'var(--text-muted)' }}>Installed</TableHead>
            <TableHead className="h-8 px-3 text-left text-xs font-semibold min-w-[120px]" style={{ color: 'var(--text-muted)' }}>CVEs</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody><SkeletonRows cols={6} /></TableBody>
      </Table>
    );
  }

  if (error) return <ErrorState message={error} onRetry={onRetry} />;

  if (patches.length === 0) {
    return <EmptyState message="No installed patches recorded in Log Analytics for this machine." />;
  }

  return (
    <div className="rounded-md border overflow-hidden" style={{ borderColor: 'var(--border)' }}>
      <Table className="w-full text-sm">
        <TableHeader>
          <TableRow>
            <TableHead className="h-8 px-3 text-left text-xs font-semibold" style={{ color: 'var(--text-muted)' }}>Name</TableHead>
            <TableHead className="h-8 px-3 text-left text-xs font-semibold w-[100px]" style={{ color: 'var(--text-muted)' }}>Version</TableHead>
            <TableHead className="h-8 px-3 text-left text-xs font-semibold w-[100px]" style={{ color: 'var(--text-muted)' }}>Category</TableHead>
            <TableHead className="h-8 px-3 text-left text-xs font-semibold w-[100px]" style={{ color: 'var(--text-muted)' }}>Publisher</TableHead>
            <TableHead className="h-8 px-3 text-left text-xs font-semibold w-[90px]" style={{ color: 'var(--text-muted)' }}>Installed</TableHead>
            <TableHead className="h-8 px-3 text-left text-xs font-semibold min-w-[120px]" style={{ color: 'var(--text-muted)' }}>CVEs</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {patches.map((p, idx) => (
            <TableRow key={`${p.SoftwareName}-${p.CurrentVersion}-${idx}`} className="border-b hover:bg-muted/50 transition-colors">
              <TableCell className="h-9 px-3 align-middle text-[13px] max-w-[220px] truncate" style={{ color: 'var(--text-primary)' }}>
                {p.SoftwareName}
              </TableCell>
              <TableCell className="h-9 px-3 align-middle font-mono text-[12px]" style={{ color: 'var(--text-secondary)' }}>
                {p.CurrentVersion || '\u2014'}
              </TableCell>
              <TableCell className="h-9 px-3 align-middle">
                <Badge variant="outline" className="text-[11px] border" style={classificationBadgeStyle(p.Category)}>
                  {p.Category || 'Other'}
                </Badge>
              </TableCell>
              <TableCell className="h-9 px-3 align-middle text-[12px] max-w-[120px] truncate" style={{ color: 'var(--text-muted)' }}>
                {p.Publisher || '\u2014'}
              </TableCell>
              <TableCell className="h-9 px-3 align-middle text-[12px]" style={{ color: 'var(--text-secondary)' }}>
                {p.InstalledDate ? formatRelativeTime(p.InstalledDate) : '\u2014'}
              </TableCell>
              <TableCell className="h-9 px-3 align-middle">
                <CveBadges cves={p.cves ?? []} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Panel Component
// ---------------------------------------------------------------------------

export function InstalledPatchesPanel({
  machine,
  open,
  onOpenChange,
}: InstalledPatchesPanelProps) {
  const [activeTab, setActiveTab] = useState<ActiveTab>('pending');

  // Pending patches (ARG)
  const [pendingPatches, setPendingPatches] = useState<readonly PendingPatch[]>([]);
  const [pendingLoading, setPendingLoading] = useState(false);
  const [pendingError, setPendingError] = useState<string | null>(null);

  // Installed patches (LAW)
  const [patches, setPatches] = useState<readonly InstalledPatch[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [days, setDays] = useState<DaysOption>('90');

  const fetchPendingPatches = useCallback(async (resourceId: string) => {
    setPendingLoading(true);
    setPendingError(null);
    try {
      const res = await fetch(
        `/api/proxy/patch/pending?resource_id=${encodeURIComponent(resourceId)}`,
        { signal: AbortSignal.timeout(15000) }
      );
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.error ?? `Request failed (${res.status})`);
      }
      const data = await res.json();
      setPendingPatches(data.patches ?? []);
    } catch (err: unknown) {
      setPendingError(err instanceof Error ? err.message : 'Failed to load pending patches');
      setPendingPatches([]);
    } finally {
      setPendingLoading(false);
    }
  }, []);

  const fetchInstalledPatches = useCallback(async (resourceId: string, daysVal: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/proxy/patch/installed?resource_id=${encodeURIComponent(resourceId)}&days=${daysVal}`,
        { signal: AbortSignal.timeout(15000) }
      );
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.error ?? `Request failed (${res.status})`);
      }
      const data = await res.json();
      setPatches(data.patches ?? []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load patch detail');
      setPatches([]);
    } finally {
      setLoading(false);
    }
  }, []);

  // Fetch when panel opens or days changes.
  // Always attempt the fetch — the LAW summary `installedCount` may be 0
  // (e.g. Arc VMs without Change Tracking) while the detail query still
  // returns results. The empty-state UI handles truly-empty responses.
  useEffect(() => {
    if (!machine || !open) return;
    fetchPatches(machine.id, days);
  }, [machine, open, days, fetchPatches]);

  // Reset state when panel closes
  useEffect(() => {
    if (!open) {
      setPendingPatches([]);
      setPendingLoading(false);
      setPendingError(null);
      setPatches([]);
      setLoading(false);
      setError(null);
      setDays('90');
      setActiveTab('pending');
    }
  }, [open]);

  // Close on Escape key
  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onOpenChange(false);
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [open, onOpenChange]);

  const handleRetry = useCallback(() => {
    if (machine) fetchPatches(machine.id, days);
  }, [machine, days, fetchPatches]);

  const handleDaysChange = useCallback((value: string) => {
    setDays(value as DaysOption);
  }, []);

  const shouldShowEmpty = !loading && !error && machine !== null && patches.length === 0;

  if (!open || !machine) return null;

  const totalPending = (machine.criticalCount ?? 0) + (machine.securityCount ?? 0);

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-30"
        style={{ background: 'rgba(0,0,0,0.3)' }}
        onClick={() => onOpenChange(false)}
      />
      {/* Side panel */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label={machine.machineName}
        className="fixed inset-y-0 right-0 z-50 flex flex-col overflow-hidden w-full max-w-2xl"
        style={{
          background: 'var(--bg-surface)',
          borderLeft: '1px solid var(--border)',
          boxShadow: '-4px 0 24px rgba(0,0,0,0.12)',
        }}
      >
        {/* Header */}
        <div className="flex items-start justify-between px-6 py-4 flex-shrink-0" style={{ borderBottom: '1px solid var(--border)' }}>
          <div>
            <h2 className="text-base font-semibold" style={{ color: 'var(--text-primary)' }}>
              {machine.machineName}
            </h2>
            <div className="flex items-center gap-2 mt-1">
              <Badge variant="secondary" className="text-xs">
                {machine.osVersion || machine.osType}
              </Badge>
              <Badge
                variant="outline"
                className="text-xs"
                style={machine.vmType === 'Arc VM'
                  ? { borderColor: 'color-mix(in srgb, var(--accent-purple) 50%, transparent)', color: 'var(--accent-purple)' }
                  : { borderColor: 'color-mix(in srgb, var(--accent-blue) 50%, transparent)', color: 'var(--accent-blue)' }
                }
              >
                {machine.vmType}
              </Badge>
              <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{machine.resourceGroup}</span>
            </div>
          </div>
          <button
            onClick={() => onOpenChange(false)}
            className="rounded-sm p-1 opacity-70 hover:opacity-100 transition-opacity"
            style={{ color: 'var(--text-secondary)' }}
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Summary strip */}
        <div className="grid grid-cols-4 gap-3 px-6 py-4" style={{ borderBottom: '1px solid var(--border)' }}>
          <StatChip label="Installed" value={machine.installedCount} />
          <StatChip label="Critical" value={machine.criticalCount} variant={machine.criticalCount > 0 ? 'danger' : 'default'} />
          <StatChip label="Security" value={machine.securityCount} variant={machine.securityCount > 0 ? 'danger' : 'default'} />
          <StatChip label="Reboot Pending" value={machine.rebootPending ? 'Yes' : 'No'} variant={machine.rebootPending ? 'warning' : 'default'} />
        </div>

        {/* Tab bar */}
        <div className="flex items-center gap-0 px-6 flex-shrink-0" style={{ borderBottom: '1px solid var(--border)' }}>
          <button
            onClick={() => setActiveTab('pending')}
            className="flex items-center gap-1.5 px-4 py-3 text-xs font-semibold transition-colors border-b-2"
            style={{
              borderBottomColor: activeTab === 'pending' ? 'var(--accent-blue)' : 'transparent',
              color: activeTab === 'pending' ? 'var(--accent-blue)' : 'var(--text-muted)',
            }}
          >
            <ShieldAlert className="h-3.5 w-3.5" />
            Pending Patches
            {totalPending > 0 && (
              <Badge className="text-[10px] px-1.5 py-0 ml-1 border" style={{
                background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
                color: 'var(--accent-red)',
                borderColor: 'color-mix(in srgb, var(--accent-red) 35%, transparent)',
              }}>
                {totalPending}
              </Badge>
            )}
          </button>
          <button
            onClick={() => setActiveTab('installed')}
            className="flex items-center gap-1.5 px-4 py-3 text-xs font-semibold transition-colors border-b-2"
            style={{
              borderBottomColor: activeTab === 'installed' ? 'var(--accent-blue)' : 'transparent',
              color: activeTab === 'installed' ? 'var(--accent-blue)' : 'var(--text-muted)',
            }}
          >
            <Package className="h-3.5 w-3.5" />
            Installed Patches
          </button>

          {/* Days selector — only shown on installed tab */}
          {activeTab === 'installed' && (
            <div className="ml-auto">
              <Select value={days} onValueChange={(v) => setDays(v as DaysOption)}>
                <SelectTrigger className="w-[120px] h-7 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {DAYS_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
        </div>

        {/* Content */}
        <ScrollArea className="flex-1">
          <div className="px-6 py-4">
            {/* Loading */}
            {loading && (
              <Table className="w-full text-sm">
                <TableHeader>
                  <TableRow>
                    <TableHead className="h-8 px-3 text-left text-xs font-semibold" style={{ color: 'var(--text-muted)' }}>Name</TableHead>
                    <TableHead className="h-8 px-3 text-left text-xs font-semibold w-[100px]" style={{ color: 'var(--text-muted)' }}>Version</TableHead>
                    <TableHead className="h-8 px-3 text-left text-xs font-semibold w-[100px]" style={{ color: 'var(--text-muted)' }}>Category</TableHead>
                    <TableHead className="h-8 px-3 text-left text-xs font-semibold w-[100px]" style={{ color: 'var(--text-muted)' }}>Publisher</TableHead>
                    <TableHead className="h-8 px-3 text-left text-xs font-semibold w-[90px]" style={{ color: 'var(--text-muted)' }}>Installed</TableHead>
                    <TableHead className="h-8 px-3 text-left text-xs font-semibold min-w-[120px]" style={{ color: 'var(--text-muted)' }}>CVEs</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <SkeletonRows />
                </TableBody>
              </Table>
            )}

            {/* Error */}
            {!loading && error && <ErrorState onRetry={handleRetry} />}

            {/* Empty — fetched but no results */}
            {shouldShowEmpty && <EmptyState />}

            {/* Patches table */}
            {!loading && !error && patches.length > 0 && (
              <div className="rounded-md border overflow-hidden" style={{ borderColor: 'var(--border)' }}>
                <Table className="w-full text-sm">
                  <TableHeader>
                    <TableRow>
                      <TableHead className="h-8 px-3 text-left text-xs font-semibold" style={{ color: 'var(--text-muted)' }}>Name</TableHead>
                      <TableHead className="h-8 px-3 text-left text-xs font-semibold w-[100px]" style={{ color: 'var(--text-muted)' }}>Version</TableHead>
                      <TableHead className="h-8 px-3 text-left text-xs font-semibold w-[100px]" style={{ color: 'var(--text-muted)' }}>Category</TableHead>
                      <TableHead className="h-8 px-3 text-left text-xs font-semibold w-[100px]" style={{ color: 'var(--text-muted)' }}>Publisher</TableHead>
                      <TableHead className="h-8 px-3 text-left text-xs font-semibold w-[90px]" style={{ color: 'var(--text-muted)' }}>Installed</TableHead>
                      <TableHead className="h-8 px-3 text-left text-xs font-semibold min-w-[120px]" style={{ color: 'var(--text-muted)' }}>CVEs</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {patches.map((p, idx) => (
                      <TableRow
                        key={`${p.SoftwareName}-${p.CurrentVersion}-${idx}`}
                        className="border-b hover:bg-muted/50 transition-colors"
                      >
                        <TableCell className="h-9 px-3 align-middle text-[13px] max-w-[220px] truncate" style={{ color: 'var(--text-primary)' }}>
                          {p.SoftwareName}
                        </TableCell>
                        <TableCell className="h-9 px-3 align-middle font-mono text-[12px]" style={{ color: 'var(--text-secondary)' }}>
                          {p.CurrentVersion || '\u2014'}
                        </TableCell>
                        <TableCell className="h-9 px-3 align-middle">
                          <Badge
                            variant="outline"
                            className="text-[11px] border"
                            style={categoryBadgeStyle(p.Category)}
                          >
                            {p.Category || 'Other'}
                          </Badge>
                        </TableCell>
                        <TableCell className="h-9 px-3 align-middle text-[12px] max-w-[120px] truncate" style={{ color: 'var(--text-muted)' }}>
                          {p.Publisher || '\u2014'}
                        </TableCell>
                        <TableCell className="h-9 px-3 align-middle text-[12px]" style={{ color: 'var(--text-secondary)' }}>
                          {p.InstalledDate ? formatRelativeTime(p.InstalledDate) : '\u2014'}
                        </TableCell>
                        <TableCell className="h-9 px-3 align-middle">
                          <CveBadges cves={p.cves ?? []} />
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </div>
        </ScrollArea>
      </div>
    </>
  );
}
