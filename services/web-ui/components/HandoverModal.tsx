'use client';

import React, { useState, useCallback } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { AlertTriangle, CheckCircle2, XCircle, Activity, Download, RefreshCw } from 'lucide-react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TopIncident {
  incident_id: string;
  title: string;
  severity: string;
  status: string;
  age_hours: number;
}

interface TopPattern {
  pattern_id: string;
  description: string;
  frequency: number;
  last_seen: string;
}

interface HandoverReportData {
  report_id: string;
  shift_start: string;
  shift_end: string;
  generated_at: string;
  open_incidents: number;
  resolved_this_shift: number;
  new_this_shift: number;
  sev0_open: number;
  sev1_open: number;
  top_open_incidents: TopIncident[];
  slo_status: string;
  slo_burn_rate: number | null;
  top_patterns: TopPattern[];
  pending_approvals: number;
  urgent_approvals: { approval_id: string; title: string; severity: string }[];
  recommended_focus: string[];
  markdown: string;
}

interface HandoverModalProps {
  open: boolean;
  onClose: () => void;
}

// ---------------------------------------------------------------------------
// Severity badge styles — semantic tokens only
// ---------------------------------------------------------------------------

function severityStyle(severity: string): React.CSSProperties {
  const s = severity.toUpperCase();
  if (s === 'SEV0') {
    return {
      background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
      color: 'var(--accent-red)',
      fontWeight: 700,
    };
  }
  if (s === 'SEV1') {
    return {
      background: 'color-mix(in srgb, var(--accent-orange) 15%, transparent)',
      color: 'var(--accent-orange)',
    };
  }
  if (s === 'SEV2') {
    return {
      background: 'color-mix(in srgb, var(--accent-yellow, var(--accent-orange)) 15%, transparent)',
      color: 'var(--accent-yellow, var(--accent-orange))',
    };
  }
  return {
    background: 'color-mix(in srgb, var(--accent-blue) 15%, transparent)',
    color: 'var(--accent-blue)',
  };
}

function sloColors(status: string): { bg: string; text: string; icon: React.ReactElement } {
  switch (status) {
    case 'healthy':
      return {
        bg: 'color-mix(in srgb, var(--accent-green) 12%, transparent)',
        text: 'var(--accent-green)',
        icon: <CheckCircle2 className="h-3.5 w-3.5" />,
      };
    case 'at_risk':
      return {
        bg: 'color-mix(in srgb, var(--accent-orange) 12%, transparent)',
        text: 'var(--accent-orange)',
        icon: <AlertTriangle className="h-3.5 w-3.5" />,
      };
    case 'breached':
      return {
        bg: 'color-mix(in srgb, var(--accent-red) 12%, transparent)',
        text: 'var(--accent-red)',
        icon: <XCircle className="h-3.5 w-3.5" />,
      };
    default:
      return {
        bg: 'color-mix(in srgb, var(--accent-blue) 12%, transparent)',
        text: 'var(--accent-blue)',
        icon: <Activity className="h-3.5 w-3.5" />,
      };
  }
}

function formatShiftTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
      timeZone: 'UTC',
    });
  } catch {
    return iso;
  }
}

// ---------------------------------------------------------------------------
// Stat chip
// ---------------------------------------------------------------------------

interface StatChipProps {
  label: string;
  value: number;
  accent?: string;
}

function StatChip({ label, value, accent = 'var(--accent-blue)' }: StatChipProps) {
  return (
    <div
      className="flex flex-col items-center justify-center rounded-lg px-4 py-3 gap-0.5 min-w-[90px]"
      style={{
        background: `color-mix(in srgb, ${accent} 10%, transparent)`,
        border: `1px solid color-mix(in srgb, ${accent} 20%, transparent)`,
      }}
    >
      <span className="text-xl font-bold tabular-nums" style={{ color: accent }}>
        {value}
      </span>
      <span className="text-[10px] font-medium uppercase tracking-wider text-center" style={{ color: 'var(--text-secondary)' }}>
        {label}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main modal component
// ---------------------------------------------------------------------------

export function HandoverModal({ open, onClose }: HandoverModalProps) {
  const [report, setReport] = useState<HandoverReportData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchReport = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/proxy/reports/shift-handover', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shift_hours: 8, format: 'json' }),
        signal: AbortSignal.timeout(30000),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body?.detail ?? body?.error ?? `Error ${res.status}`);
      }
      const data = await res.json() as HandoverReportData;
      setReport(data);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to generate report';
      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  // Fetch when modal opens (only once per open)
  const handleOpenChange = useCallback(
    (isOpen: boolean) => {
      if (isOpen && !report && !loading) {
        void fetchReport();
      }
      if (!isOpen) {
        onClose();
      }
    },
    [report, loading, fetchReport, onClose],
  );

  // Also fetch on first open
  React.useEffect(() => {
    if (open && !report && !loading && !error) {
      void fetchReport();
    }
    // Reset when modal closes
    if (!open) {
      setReport(null);
      setError(null);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const downloadMarkdown = useCallback(() => {
    if (!report?.markdown) return;
    const blob = new Blob([report.markdown], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `handover-${report.report_id}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }, [report]);

  const slo = sloColors(report?.slo_status ?? 'unknown');

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        className="max-w-2xl max-h-[90vh] overflow-y-auto"
        style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border)' }}
      >
        <DialogHeader>
          <DialogTitle style={{ color: 'var(--text-primary)' }}>
            📋 Operator Shift Handover Report
          </DialogTitle>
        </DialogHeader>

        {/* ---------------------------------------------------------------- */}
        {/* Loading state                                                      */}
        {/* ---------------------------------------------------------------- */}
        {loading && (
          <div className="flex flex-col gap-4 py-4">
            <Skeleton className="h-5 w-64" />
            <div className="flex gap-3">
              <Skeleton className="h-16 w-24 rounded-lg" />
              <Skeleton className="h-16 w-24 rounded-lg" />
              <Skeleton className="h-16 w-24 rounded-lg" />
              <Skeleton className="h-16 w-24 rounded-lg" />
            </div>
            <Skeleton className="h-24 w-full rounded-lg" />
            <Skeleton className="h-32 w-full rounded-lg" />
          </div>
        )}

        {/* ---------------------------------------------------------------- */}
        {/* Error state                                                        */}
        {/* ---------------------------------------------------------------- */}
        {!loading && error && (
          <div className="py-4 flex flex-col gap-4">
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
            <button
              onClick={() => void fetchReport()}
              className="self-start flex items-center gap-2 text-sm px-3 py-1.5 rounded"
              style={{
                background: 'color-mix(in srgb, var(--accent-blue) 12%, transparent)',
                color: 'var(--accent-blue)',
              }}
            >
              <RefreshCw className="h-4 w-4" />
              Retry
            </button>
          </div>
        )}

        {/* ---------------------------------------------------------------- */}
        {/* Report content                                                     */}
        {/* ---------------------------------------------------------------- */}
        {!loading && !error && report && (
          <div className="flex flex-col gap-5 py-2">
            {/* Shift period */}
            <div
              className="rounded-lg px-4 py-2.5 text-[13px]"
              style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)' }}
            >
              <span style={{ color: 'var(--text-secondary)' }}>Shift: </span>
              <span className="font-semibold" style={{ color: 'var(--text-primary)' }}>
                {formatShiftTime(report.shift_start)} → {formatShiftTime(report.shift_end)} UTC
              </span>
              <span className="ml-3 text-[11px]" style={{ color: 'var(--text-secondary)' }}>
                Generated {formatShiftTime(report.generated_at)}
              </span>
            </div>

            {/* Stat chips */}
            <div className="flex flex-wrap gap-3">
              <StatChip label="Open" value={report.open_incidents} accent="var(--accent-blue)" />
              <StatChip label="Resolved" value={report.resolved_this_shift} accent="var(--accent-green)" />
              <StatChip label="New" value={report.new_this_shift} accent="var(--accent-orange)" />
              <StatChip label="Approvals" value={report.pending_approvals} accent={report.pending_approvals > 0 ? 'var(--accent-red)' : 'var(--accent-blue)'} />
            </div>

            {/* SLO status */}
            <div className="flex items-center gap-2">
              <span className="text-[12px] font-medium uppercase tracking-wider" style={{ color: 'var(--text-secondary)' }}>
                SLO Status
              </span>
              <span
                className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[12px] font-semibold"
                style={{ background: slo.bg, color: slo.text }}
              >
                <span style={{ color: slo.text }}>{slo.icon}</span>
                {report.slo_status.toUpperCase()}
                {report.slo_burn_rate !== null && (
                  <span className="font-normal ml-1">
                    (burn rate: {report.slo_burn_rate.toFixed(2)})
                  </span>
                )}
              </span>
            </div>

            {/* Top open incidents */}
            {report.top_open_incidents.length > 0 && (
              <div
                className="rounded-lg overflow-hidden"
                style={{ border: '1px solid var(--border)' }}
              >
                <div
                  className="px-4 py-2 text-[11px] font-semibold uppercase tracking-wider"
                  style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)', color: 'var(--text-secondary)' }}
                >
                  Top Open Incidents
                </div>
                <table className="w-full text-[12px]">
                  <thead>
                    <tr style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
                      <th className="text-left px-3 py-2 font-medium" style={{ color: 'var(--text-secondary)' }}>Sev</th>
                      <th className="text-left px-3 py-2 font-medium" style={{ color: 'var(--text-secondary)' }}>Title</th>
                      <th className="text-right px-3 py-2 font-medium" style={{ color: 'var(--text-secondary)' }}>Age</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.top_open_incidents.slice(0, 5).map((inc, i) => (
                      <tr
                        key={inc.incident_id || i}
                        style={{ borderBottom: '1px solid var(--border)' }}
                      >
                        <td className="px-3 py-2">
                          <span
                            className="inline-block px-2 py-0.5 rounded text-[11px] font-semibold"
                            style={severityStyle(inc.severity)}
                          >
                            {inc.severity}
                          </span>
                        </td>
                        <td className="px-3 py-2" style={{ color: 'var(--text-primary)' }}>
                          {inc.title}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums" style={{ color: 'var(--text-secondary)' }}>
                          {inc.age_hours.toFixed(1)}h
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Top patterns */}
            {report.top_patterns.length > 0 && (
              <div
                className="rounded-lg p-4"
                style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
              >
                <div className="text-[11px] font-semibold uppercase tracking-wider mb-2" style={{ color: 'var(--text-secondary)' }}>
                  Recurring Patterns
                </div>
                <ul className="flex flex-col gap-1.5">
                  {report.top_patterns.slice(0, 3).map((p, i) => (
                    <li key={p.pattern_id || i} className="flex items-start gap-2 text-[12px]">
                      <span style={{ color: 'var(--accent-orange)' }}>🔁</span>
                      <span style={{ color: 'var(--text-primary)' }}>
                        <span className="font-medium">{p.description}</span>
                        <span style={{ color: 'var(--text-secondary)' }}> — {p.frequency}/wk</span>
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Recommended focus */}
            {report.recommended_focus.length > 0 && (
              <div
                className="rounded-lg p-4"
                style={{
                  background: 'color-mix(in srgb, var(--accent-blue) 6%, transparent)',
                  border: '1px solid color-mix(in srgb, var(--accent-blue) 20%, transparent)',
                }}
              >
                <div className="text-[11px] font-semibold uppercase tracking-wider mb-2" style={{ color: 'var(--accent-blue)' }}>
                  Recommended Focus
                </div>
                <ul className="flex flex-col gap-1.5">
                  {report.recommended_focus.map((item, i) => (
                    <li key={i} className="text-[12px]" style={{ color: 'var(--text-primary)' }}>
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        <DialogFooter className="flex gap-2 pt-2">
          {report && (
            <button
              onClick={downloadMarkdown}
              className="flex items-center gap-1.5 text-[12px] px-3 py-1.5 rounded"
              style={{
                background: 'color-mix(in srgb, var(--accent-blue) 10%, transparent)',
                color: 'var(--accent-blue)',
                border: '1px solid color-mix(in srgb, var(--accent-blue) 25%, transparent)',
              }}
            >
              <Download className="h-3.5 w-3.5" />
              Download Markdown
            </button>
          )}
          <button
            onClick={onClose}
            className="text-[12px] px-3 py-1.5 rounded"
            style={{
              background: 'var(--bg-subtle)',
              color: 'var(--text-secondary)',
              border: '1px solid var(--border)',
            }}
          >
            Close
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
