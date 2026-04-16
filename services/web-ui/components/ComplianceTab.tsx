'use client';

import React, { useEffect, useState, useCallback, useRef } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { useResizable } from '@/lib/use-resizable';
import { FileCheck, RefreshCw, Download, X } from 'lucide-react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ComplianceFinding {
  finding_type: string;
  defender_rule_id: string;
  display_name: string;
  severity: string;
}

interface ComplianceControl {
  framework: string;
  control_id: string;
  control_title: string;
  status: 'passing' | 'failing' | 'not_assessed';
  findings: ComplianceFinding[];
}

interface FrameworkScore {
  score: number;
  total_controls: number;
  passing: number;
  failing: number;
  not_assessed: number;
}

interface PostureResponse {
  subscription_id: string;
  generated_at: string;
  cache_hit?: boolean;
  frameworks: {
    asb?: FrameworkScore;
    cis?: FrameworkScore;
    nist?: FrameworkScore;
  };
  controls: ComplianceControl[];
  error?: string;
}

type FrameworkFilter = 'all' | 'asb' | 'cis' | 'nist';

interface ComplianceTabProps {
  subscriptions: string[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function scoreColor(score: number): string {
  if (score >= 70) return 'var(--accent-green)';
  if (score >= 40) return 'var(--accent-orange, #d97706)';
  return 'var(--accent-red)';
}

function controlBg(status: ComplianceControl['status']): string {
  switch (status) {
    case 'passing':
      return 'color-mix(in srgb, var(--accent-green) 55%, transparent)';
    case 'failing':
      return 'color-mix(in srgb, var(--accent-red) 55%, transparent)';
    default:
      return 'color-mix(in srgb, var(--border) 60%, transparent)';
  }
}

function severityBadgeStyle(severity: string): React.CSSProperties {
  switch (severity.toLowerCase()) {
    case 'high':
      return {
        background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
        color: 'var(--accent-red)',
        border: '1px solid color-mix(in srgb, var(--accent-red) 30%, transparent)',
      };
    case 'medium':
      return {
        background: 'color-mix(in srgb, var(--accent-orange, #d97706) 15%, transparent)',
        color: 'var(--accent-orange, #d97706)',
        border: '1px solid color-mix(in srgb, var(--accent-orange, #d97706) 30%, transparent)',
      };
    default:
      return {
        background: 'color-mix(in srgb, var(--accent-blue) 15%, transparent)',
        color: 'var(--accent-blue)',
        border: '1px solid color-mix(in srgb, var(--accent-blue) 30%, transparent)',
      };
  }
}

const FRAMEWORK_LABELS: Record<string, string> = {
  asb: 'Azure Security Benchmark v3',
  cis: 'CIS v8',
  nist: 'NIST 800-53 Rev 5',
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ComplianceTab({ subscriptions }: ComplianceTabProps) {
  const [posture, setPosture] = useState<PostureResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedFramework, setSelectedFramework] = useState<FrameworkFilter>('all');
  const [selectedControl, setSelectedControl] = useState<ComplianceControl | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);

  const fetchPosture = useCallback(async () => {
    if (subscriptions.length === 0) return;

    setLoading(true);
    setError(null);

    try {
      const subId = subscriptions[0];
      const res = await fetch(
        `/api/proxy/compliance/posture?subscription_id=${encodeURIComponent(subId)}`,
        { signal: AbortSignal.timeout(20000) }
      );
      const data: PostureResponse = await res.json();

      if (!res.ok) {
        setError(data.error ?? `Failed to load compliance posture (${res.status})`);
        return;
      }

      setPosture(data);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      setError(`Unable to load compliance data. Check that the API gateway is running. (${message})`);
    } finally {
      setLoading(false);
    }
  }, [subscriptions]);

  useEffect(() => {
    fetchPosture();
  }, [fetchPosture]);

  // ---------------------------------------------------------------------------
  // Drag-to-reposition + resize hooks — MUST be before any early returns
  // ---------------------------------------------------------------------------
  const { width: detailPanelWidth, onMouseDown: resizeOnMouseDown } = useResizable({
    minWidth: 380,
    maxWidth: 800,
    defaultWidth: 520,
    storageKey: 'compliance-detail-panel-width',
  })
  const [detailPosition, setDetailPosition] = useState<{ x: number; y: number } | null>(null)
  const detailDragState = useRef({ isDragging: false, startX: 0, startY: 0, originX: 0, originY: 0 })

  const handleDetailHeaderMouseDown = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (e.button !== 0) return
    e.preventDefault()
    detailDragState.current = {
      isDragging: true,
      startX: e.clientX,
      startY: e.clientY,
      originX: detailPosition?.x ?? 0,
      originY: detailPosition?.y ?? 0,
    }
  }, [detailPosition])

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (!detailDragState.current.isDragging) return
      const dx = e.clientX - detailDragState.current.startX
      const dy = e.clientY - detailDragState.current.startY
      setDetailPosition({ x: detailDragState.current.originX + dx, y: detailDragState.current.originY + dy })
    }
    const onMouseUp = () => { detailDragState.current.isDragging = false }
    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)
    return () => {
      document.removeEventListener('mousemove', onMouseMove)
      document.removeEventListener('mouseup', onMouseUp)
    }
  }, [])

  function handleExport(format: 'csv' | 'pdf') {
    if (subscriptions.length === 0) return;
    const subId = encodeURIComponent(subscriptions[0]);
    const fwParam = selectedFramework !== 'all' ? `&framework=${selectedFramework}` : '';
    window.open(
      `/api/proxy/compliance/export?subscription_id=${subId}&format=${format}${fwParam}`,
      '_blank'
    );
  }

  function handleCellClick(ctrl: ComplianceControl) {
    setSelectedControl(ctrl);
    setSheetOpen(true);
  }

  // ---------------------------------------------------------------------------
  // Early returns (after all hooks)
  // ---------------------------------------------------------------------------
  if (subscriptions.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 gap-3">
        <FileCheck className="h-8 w-8" style={{ color: 'var(--text-muted)' }} />
        <p className="text-[13px]" style={{ color: 'var(--text-muted)' }}>
          Select a subscription to view compliance posture
        </p>
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Loading skeleton
  // ---------------------------------------------------------------------------
  if (loading && !posture) {
    return (
      <div className="flex flex-col gap-3 px-4 py-4">
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Error state
  // ---------------------------------------------------------------------------
  if (error && !posture) {
    return (
      <div className="px-4 py-4">
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      </div>
    );
  }

  const frameworks = posture?.frameworks ?? {};
  const allControls = posture?.controls ?? [];
  const filteredControls =
    selectedFramework === 'all'
      ? allControls
      : allControls.filter((c) => c.framework === selectedFramework);

  return (
    <>
      <div className="flex flex-col h-full">
      {/* ---- Header ---- */}
      <div
        className="flex items-center gap-2 px-4 py-3 flex-wrap"
        style={{ borderBottom: '1px solid var(--border)' }}
      >
        <FileCheck className="h-4 w-4 shrink-0" style={{ color: 'var(--accent-blue)' }} />
        <span className="text-[13px] font-medium" style={{ color: 'var(--text-primary)' }}>
          Compliance Posture
        </span>

        {/* Framework selector */}
        <div className="flex gap-1 ml-2">
          {(['all', 'asb', 'cis', 'nist'] as FrameworkFilter[]).map((fw) => (
            <Button
              key={fw}
              variant={selectedFramework === fw ? 'default' : 'ghost'}
              size="sm"
              className="h-6 px-2 text-[11px]"
              onClick={() => setSelectedFramework(fw)}
            >
              {fw === 'all' ? 'All' : fw.toUpperCase()}
            </Button>
          ))}
        </div>

        <div className="flex-1" />

        {/* Refresh */}
        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2"
          onClick={fetchPosture}
          disabled={loading}
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
        </Button>

        {/* Export CSV */}
        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-[11px] gap-1"
          onClick={() => handleExport('csv')}
        >
          <Download className="h-3 w-3" />
          CSV
        </Button>

        {/* Export PDF */}
        <Button
          variant="outline"
          size="sm"
          className="h-7 px-2 text-[11px] gap-1"
          onClick={() => handleExport('pdf')}
        >
          <Download className="h-3 w-3" />
          PDF
        </Button>
      </div>

      {/* ---- Score cards ---- */}
      <div className="grid grid-cols-3 gap-3 px-4 pt-4">
        {(['asb', 'cis', 'nist'] as const).map((fw) => {
          const stats = frameworks[fw];
          if (!stats) return null;
          return (
            <Card key={fw} className="overflow-hidden">
              <CardContent className="px-4 py-3">
                <p className="text-[10px] font-medium uppercase tracking-wide mb-1" style={{ color: 'var(--text-muted)' }}>
                  {fw.toUpperCase()}
                </p>
                <p
                  className="text-[28px] font-semibold leading-none mb-1"
                  style={{ color: scoreColor(stats.score) }}
                >
                  {stats.score.toFixed(1)}%
                </p>
                <p className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
                  {stats.passing} passing · {stats.failing} failing · {stats.not_assessed} n/a
                </p>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* ---- Heat-map ---- */}
      <div className="px-4 pt-4 pb-4 flex-1 overflow-y-auto">
        <p className="text-[13px] font-medium mb-2" style={{ color: 'var(--text-primary)' }}>
          Control Status Heat Map
          {posture?.cache_hit && (
            <span className="ml-2 text-[10px] font-normal" style={{ color: 'var(--text-muted)' }}>
              (cached)
            </span>
          )}
        </p>

        {filteredControls.length === 0 ? (
          <p className="text-[12px]" style={{ color: 'var(--text-muted)' }}>
            No controls to display for this selection.
          </p>
        ) : (
          <div
            className="grid gap-1"
            style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(52px, 1fr))' }}
          >
            {filteredControls.map((ctrl) => (
              <div
                key={`${ctrl.framework}-${ctrl.control_id}`}
                className="h-8 rounded text-[8px] flex items-center justify-center font-mono cursor-pointer hover:opacity-80 hover:ring-1 hover:ring-foreground/20 transition-opacity"
                style={{ background: controlBg(ctrl.status) }}
                title={`${ctrl.control_id}: ${ctrl.control_title} (${ctrl.status})`}
                onClick={() => handleCellClick(ctrl)}
              >
                {ctrl.control_id}
              </div>
            ))}
          </div>
        )}

        {/* Legend */}
        <div className="flex gap-4 mt-3">
          {[
            { label: 'Passing', bg: 'color-mix(in srgb, var(--accent-green) 55%, transparent)' },
            { label: 'Failing', bg: 'color-mix(in srgb, var(--accent-red) 55%, transparent)' },
            { label: 'Not Assessed', bg: 'color-mix(in srgb, var(--border) 60%, transparent)' },
          ].map(({ label, bg }) => (
            <div key={label} className="flex items-center gap-1.5">
              <div className="w-3 h-3 rounded-sm" style={{ background: bg }} />
              <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
                {label}
              </span>
            </div>
          ))}
        </div>
      </div>

      </div>{/* end outer flex */}

      {/* ---- Findings Panel (draggable + resizable) ---- */}
      {sheetOpen && selectedControl && (
        <>
          <div className="fixed inset-0 z-30" style={{ background: 'rgba(0,0,0,0.2)' }} onClick={() => setSheetOpen(false)} />
          <div
            role="dialog"
            aria-modal="true"
            className="fixed inset-y-0 right-0 z-50 flex flex-col overflow-hidden"
            style={{
              width: `${detailPanelWidth}px`,
              background: 'var(--bg-surface)',
              borderLeft: '1px solid var(--border)',
              boxShadow: '-4px 0 24px rgba(0,0,0,0.12)',
              transform: detailPosition ? `translate(${detailPosition.x}px, ${detailPosition.y}px)` : undefined,
            }}
          >
            <div className="absolute left-0 top-0 bottom-0 w-1.5 z-10 cursor-col-resize hover:bg-primary/20 transition-colors" onMouseDown={resizeOnMouseDown} />
            <div
              className="flex items-start justify-between px-5 py-4 flex-shrink-0 select-none"
              style={{ borderBottom: '1px solid var(--border)', cursor: 'grab' }}
              onMouseDown={handleDetailHeaderMouseDown}
            >
              <div>
                <p className="text-[14px] font-semibold" style={{ color: 'var(--text-primary)' }}>
                  {selectedControl.control_id} — {selectedControl.framework.toUpperCase()}
                </p>
                <p className="text-[12px] mt-0.5" style={{ color: 'var(--text-muted)' }}>{selectedControl.control_title}</p>
                <div className="flex gap-2 mt-2">
                  <Badge style={{
                    background: selectedControl.status === 'passing' ? 'color-mix(in srgb, var(--accent-green) 15%, transparent)' : selectedControl.status === 'failing' ? 'color-mix(in srgb, var(--accent-red) 15%, transparent)' : 'color-mix(in srgb, var(--border) 40%, transparent)',
                    color: selectedControl.status === 'passing' ? 'var(--accent-green)' : selectedControl.status === 'failing' ? 'var(--accent-red)' : 'var(--text-muted)',
                    border: 'none',
                  }}>
                    {selectedControl.status.replace('_', ' ')}
                  </Badge>
                  <Badge variant="outline" className="text-[10px]">{FRAMEWORK_LABELS[selectedControl.framework] ?? selectedControl.framework}</Badge>
                </div>
              </div>
              <button
                onClick={() => setSheetOpen(false)}
                onMouseDown={(e) => e.stopPropagation()}
                className="p-1 rounded opacity-70 hover:opacity-100 transition-opacity flex-shrink-0"
                style={{ color: 'var(--text-secondary)', cursor: 'default' }}
                aria-label="Close"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-5">
              <p className="text-[12px] font-medium mb-2" style={{ color: 'var(--text-primary)' }}>Findings ({selectedControl.findings.length})</p>
              {selectedControl.findings.length === 0 ? (
                <p className="text-[12px]" style={{ color: 'var(--text-muted)' }}>No findings mapped to this control.</p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="text-[11px] h-8">Finding</TableHead>
                      <TableHead className="text-[11px] h-8 w-24">Type</TableHead>
                      <TableHead className="text-[11px] h-8 w-20">Severity</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {selectedControl.findings.map((finding, i) => (
                      <TableRow key={i}>
                        <TableCell className="text-[11px] py-2">{finding.display_name}</TableCell>
                        <TableCell className="text-[10px] py-2" style={{ color: 'var(--text-muted)' }}>{finding.finding_type.replace('_', ' ')}</TableCell>
                        <TableCell className="py-2">
                          <span className="text-[10px] px-1.5 py-0.5 rounded" style={severityBadgeStyle(finding.severity)}>{finding.severity}</span>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </div>
          </div>
        </>
      )}
    </>
  );
}
