'use client';

import React, { useEffect, useState, useCallback } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
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
import { Package, AlertTriangle, RefreshCw } from 'lucide-react';
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

interface InstalledPatchesPanelProps {
  readonly machine: PanelMachine | null;
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type DaysOption = '30' | '90' | '180' | '365';

const DAYS_OPTIONS: readonly { readonly value: DaysOption; readonly label: string }[] = [
  { value: '30', label: '30 days' },
  { value: '90', label: '90 days' },
  { value: '180', label: '180 days' },
  { value: '365', label: '365 days' },
] as const;

function categoryBadgeClass(category: string): string {
  const lower = category.toLowerCase();
  if (lower === 'security') {
    return 'bg-red-900/40 text-red-400 border-red-700/50 border';
  }
  if (lower === 'critical') {
    return 'bg-orange-900/40 text-orange-400 border-orange-700/50 border';
  }
  return '';
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
  const bgMap = {
    default: 'bg-zinc-800 border-zinc-700',
    warning: 'bg-orange-900/30 border-orange-700/50',
    danger: 'bg-red-900/30 border-red-700/50',
  } as const;

  const textMap = {
    default: 'text-zinc-100',
    warning: 'text-orange-400',
    danger: 'text-red-400',
  } as const;

  const v = variant ?? 'default';

  return (
    <div className={`flex flex-col items-center rounded-lg border px-4 py-2.5 ${bgMap[v]}`}>
      <span className={`font-mono text-lg font-semibold ${textMap[v]}`}>{value}</span>
      <span className="text-[11px] text-zinc-500">{label}</span>
    </div>
  );
}

function CveBadges({ cves }: { readonly cves: readonly string[] }) {
  if (cves.length === 0) {
    return <span className="text-zinc-600">&mdash;</span>;
  }

  const visible = cves.slice(0, MAX_VISIBLE_CVES);
  const overflow = cves.length - MAX_VISIBLE_CVES;

  return (
    <div className="flex flex-wrap gap-1">
      {visible.map((cve) => (
        <Badge
          key={cve}
          variant="outline"
          className="text-[10px] font-mono px-1.5 py-0 text-zinc-400 border-zinc-700"
        >
          {cve}
        </Badge>
      ))}
      {overflow > 0 && (
        <Badge
          variant="outline"
          className="text-[10px] font-mono px-1.5 py-0 text-zinc-500 border-zinc-700"
        >
          +{overflow} more
        </Badge>
      )}
    </div>
  );
}

function SkeletonRows() {
  return (
    <>
      {Array.from({ length: 3 }).map((_, i) => (
        <TableRow key={i}>
          <TableCell colSpan={6} className="px-3 py-2">
            <Skeleton className="h-6 w-full" />
          </TableCell>
        </TableRow>
      ))}
    </>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-12 gap-3">
      <Package className="h-8 w-8 text-zinc-600" />
      <p className="text-sm text-zinc-400 text-center max-w-[320px]">
        No installed patches recorded in Log Analytics for this machine.
      </p>
    </div>
  );
}

function ErrorState({ onRetry }: { readonly onRetry: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 gap-3">
      <AlertTriangle className="h-8 w-8 text-red-500" />
      <p className="text-sm text-zinc-400">Failed to load patch detail.</p>
      <Button variant="outline" size="sm" onClick={onRetry}>
        <RefreshCw className="h-3.5 w-3.5 mr-1" />
        Try again
      </Button>
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
  const [patches, setPatches] = useState<readonly InstalledPatch[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [days, setDays] = useState<DaysOption>('90');

  const fetchPatches = useCallback(async (resourceId: string, daysVal: string) => {
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
      const message = err instanceof Error ? err.message : 'Failed to load patch detail';
      setError(message);
      setPatches([]);
    } finally {
      setLoading(false);
    }
  }, []);

  // Fetch when panel opens or days changes
  useEffect(() => {
    if (!machine || !open) return;
    // Skip fetch if the machine has no installed patches
    if (machine.installedCount === 0) {
      setPatches([]);
      setLoading(false);
      setError(null);
      return;
    }
    fetchPatches(machine.id, days);
  }, [machine, open, days, fetchPatches]);

  // Reset state when panel closes
  useEffect(() => {
    if (!open) {
      setPatches([]);
      setLoading(false);
      setError(null);
      setDays('90');
    }
  }, [open]);

  const handleRetry = useCallback(() => {
    if (machine) {
      fetchPatches(machine.id, days);
    }
  }, [machine, days, fetchPatches]);

  const handleDaysChange = useCallback((value: string) => {
    setDays(value as DaysOption);
  }, []);

  const shouldShowEmpty = !loading && !error && machine !== null && machine.installedCount === 0;
  const shouldShowFetchedEmpty = !loading && !error && patches.length === 0 && machine !== null && machine.installedCount > 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="fixed inset-y-0 right-0 left-auto translate-x-0 translate-y-0 top-0 h-full w-full max-w-2xl rounded-none border-l border-zinc-800 bg-zinc-900 p-0 data-[state=open]:slide-in-from-right data-[state=closed]:slide-out-to-right data-[state=open]:animate-in data-[state=closed]:animate-out duration-300 sm:rounded-none"
      >
        {machine && (
          <div className="flex h-full flex-col">
            {/* Header */}
            <DialogHeader className="border-b border-zinc-800 px-6 py-4">
              <DialogTitle className="text-base font-semibold text-zinc-100">
                {machine.machineName}
              </DialogTitle>
              <DialogDescription asChild>
                <div className="flex items-center gap-2 mt-1">
                  <Badge variant="secondary" className="text-xs">
                    {machine.osVersion || machine.osType}
                  </Badge>
                  <Badge
                    variant="outline"
                    className={machine.vmType === 'Arc VM'
                      ? 'text-xs border-purple-500/50 text-purple-400'
                      : 'text-xs border-blue-500/50 text-blue-400'
                    }
                  >
                    {machine.vmType}
                  </Badge>
                  <span className="text-xs text-zinc-500">
                    {machine.resourceGroup}
                  </span>
                </div>
              </DialogDescription>
            </DialogHeader>

            {/* Summary strip */}
            <div className="grid grid-cols-4 gap-3 px-6 py-4 border-b border-zinc-800">
              <StatChip label="Installed" value={machine.installedCount} />
              <StatChip
                label="Critical"
                value={machine.criticalCount}
                variant={machine.criticalCount > 0 ? 'danger' : 'default'}
              />
              <StatChip
                label="Security"
                value={machine.securityCount}
                variant={machine.securityCount > 0 ? 'danger' : 'default'}
              />
              <StatChip
                label="Reboot Pending"
                value={machine.rebootPending ? 'Yes' : 'No'}
                variant={machine.rebootPending ? 'warning' : 'default'}
              />
            </div>

            {/* Days selector */}
            <div className="flex items-center justify-between px-6 py-3 border-b border-zinc-800">
              <span className="text-xs font-semibold text-zinc-400">
                Installed Patches
              </span>
              <Select value={days} onValueChange={handleDaysChange}>
                <SelectTrigger className="w-[120px] h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {DAYS_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Patch table or state */}
            <ScrollArea className="flex-1">
              <div className="px-6 py-4">
                {/* Loading */}
                {loading && (
                  <Table className="w-full text-sm">
                    <TableHeader>
                      <TableRow>
                        <TableHead className="h-8 px-3 text-left text-xs font-semibold text-zinc-500">Name</TableHead>
                        <TableHead className="h-8 px-3 text-left text-xs font-semibold text-zinc-500 w-[100px]">Version</TableHead>
                        <TableHead className="h-8 px-3 text-left text-xs font-semibold text-zinc-500 w-[100px]">Category</TableHead>
                        <TableHead className="h-8 px-3 text-left text-xs font-semibold text-zinc-500 w-[100px]">Publisher</TableHead>
                        <TableHead className="h-8 px-3 text-left text-xs font-semibold text-zinc-500 w-[90px]">Installed</TableHead>
                        <TableHead className="h-8 px-3 text-left text-xs font-semibold text-zinc-500 min-w-[120px]">CVEs</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      <SkeletonRows />
                    </TableBody>
                  </Table>
                )}

                {/* Error */}
                {!loading && error && <ErrorState onRetry={handleRetry} />}

                {/* Empty — no LAW data (installedCount === 0, no fetch) */}
                {shouldShowEmpty && <EmptyState />}

                {/* Empty — fetched but no results */}
                {shouldShowFetchedEmpty && <EmptyState />}

                {/* Patches table */}
                {!loading && !error && patches.length > 0 && (
                  <div className="rounded-md border border-zinc-800 overflow-hidden">
                    <Table className="w-full text-sm">
                      <TableHeader>
                        <TableRow>
                          <TableHead className="h-8 px-3 text-left text-xs font-semibold text-zinc-500">Name</TableHead>
                          <TableHead className="h-8 px-3 text-left text-xs font-semibold text-zinc-500 w-[100px]">Version</TableHead>
                          <TableHead className="h-8 px-3 text-left text-xs font-semibold text-zinc-500 w-[100px]">Category</TableHead>
                          <TableHead className="h-8 px-3 text-left text-xs font-semibold text-zinc-500 w-[100px]">Publisher</TableHead>
                          <TableHead className="h-8 px-3 text-left text-xs font-semibold text-zinc-500 w-[90px]">Installed</TableHead>
                          <TableHead className="h-8 px-3 text-left text-xs font-semibold text-zinc-500 min-w-[120px]">CVEs</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {patches.map((p, idx) => (
                          <TableRow
                            key={`${p.SoftwareName}-${p.CurrentVersion}-${idx}`}
                            className="border-b border-zinc-800 hover:bg-zinc-800/50 transition-colors"
                          >
                            <TableCell className="h-9 px-3 align-middle text-[13px] text-zinc-200 max-w-[220px] truncate">
                              {p.SoftwareName}
                            </TableCell>
                            <TableCell className="h-9 px-3 align-middle font-mono text-[12px] text-zinc-400">
                              {p.CurrentVersion || '\u2014'}
                            </TableCell>
                            <TableCell className="h-9 px-3 align-middle">
                              <Badge
                                variant="outline"
                                className={`text-[11px] ${categoryBadgeClass(p.Category)}`}
                              >
                                {p.Category || 'Other'}
                              </Badge>
                            </TableCell>
                            <TableCell className="h-9 px-3 align-middle text-[12px] text-zinc-500 max-w-[120px] truncate">
                              {p.Publisher || '\u2014'}
                            </TableCell>
                            <TableCell className="h-9 px-3 align-middle text-[12px] text-zinc-400">
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
        )}
      </DialogContent>
    </Dialog>
  );
}
