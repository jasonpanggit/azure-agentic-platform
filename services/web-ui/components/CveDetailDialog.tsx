'use client';

import React from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { ScrollArea } from '@/components/ui/scroll-area';
import { ExternalLink, ChevronDown, ChevronUp } from 'lucide-react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface CveDetail {
  cveNumber: string;
  cveTitle: string;
  severity: string;
  baseScore: string;
  temporalScore: string;
  vectorString: string;
  impact: string;
  vulnType: string;
  description: string;
  exploited: string;
  publiclyDisclosed: string;
  releaseDate: string;
  mitreUrl: string;
  latestSoftwareRelease: string;
  tag: string;
}

// ---------------------------------------------------------------------------
// CVSS helpers
// ---------------------------------------------------------------------------

export function severityColor(severity: string): string {
  switch (severity.toLowerCase()) {
    case 'critical': return 'var(--accent-red)';
    case 'important': return 'var(--accent-orange, #f97316)';
    case 'moderate': return 'var(--accent-yellow, #eab308)';
    default: return 'var(--text-muted)';
  }
}

interface CvssComponents {
  AV: string; AC: string; PR: string; UI: string;
  S: string; C: string; I: string; A: string;
}

const CVSS_LABELS: Record<keyof CvssComponents, string> = {
  AV: 'Attack Vector', AC: 'Attack Complexity', PR: 'Privileges Required',
  UI: 'User Interaction', S: 'Scope', C: 'Confidentiality',
  I: 'Integrity', A: 'Availability',
};

const CVSS_VALUE_SCORES: Record<string, Record<string, number>> = {
  AV: { N: 1.0, A: 0.67, L: 0.55, P: 0.2 },
  AC: { L: 1.0, H: 0.44 },
  PR: { N: 1.0, L: 0.62, H: 0.27 },
  UI: { N: 1.0, R: 0.85 },
  S: { C: 1.0, U: 0.5 },
  C: { H: 1.0, L: 0.5, N: 0 },
  I: { H: 1.0, L: 0.5, N: 0 },
  A: { H: 1.0, L: 0.5, N: 0 },
};

const CVSS_VALUE_LABELS: Record<string, Record<string, string>> = {
  AV: { N: 'Network', A: 'Adjacent', L: 'Local', P: 'Physical' },
  AC: { L: 'Low', H: 'High' },
  PR: { N: 'None', L: 'Low', H: 'High' },
  UI: { N: 'None', R: 'Required' },
  S: { C: 'Changed', U: 'Unchanged' },
  C: { H: 'High', L: 'Low', N: 'None' },
  I: { H: 'High', L: 'Low', N: 'None' },
  A: { H: 'High', L: 'Low', N: 'None' },
};

function parseCvssVector(vectorString: string): Partial<CvssComponents> {
  const result: Partial<CvssComponents> = {};
  const parts = vectorString.replace(/^CVSS:\d+\.\d+\//, '').split('/');
  for (const part of parts) {
    const [key, val] = part.split(':');
    if (key && val && key in CVSS_LABELS) {
      (result as Record<string, string>)[key] = val;
    }
  }
  return result;
}

function scoreToColor(score: number): string {
  if (score >= 0.8) return 'var(--accent-red)';
  if (score >= 0.5) return 'var(--accent-orange, #f97316)';
  if (score >= 0.3) return 'var(--accent-yellow, #eab308)';
  return 'var(--accent-green, #22c55e)';
}

// ---------------------------------------------------------------------------
// CVSS visualisation sub-components
// ---------------------------------------------------------------------------

function CvssBar({ label, value, score }: { label: string; value: string; score: number }) {
  const pct = Math.round(score * 100);
  const color = scoreToColor(score);
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-[130px] shrink-0" style={{ color: 'var(--text-muted)' }}>{label}</span>
      <span className="w-[72px] shrink-0 font-medium" style={{ color: 'var(--text-secondary)' }}>{value}</span>
      <div className="flex-1 rounded-full overflow-hidden" style={{ height: 5, background: 'var(--border)' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 9999, transition: 'width 0.3s' }} />
      </div>
    </div>
  );
}

function CvssRadar({ components }: { components: Partial<CvssComponents> }) {
  const keys = Object.keys(CVSS_LABELS) as (keyof CvssComponents)[];
  const n = keys.length;
  const cx = 80, cy = 80, r = 60;

  const points = (scale: number) =>
    keys.map((_, i) => {
      const angle = (2 * Math.PI * i) / n - Math.PI / 2;
      return [cx + r * scale * Math.cos(angle), cy + r * scale * Math.sin(angle)];
    });

  const toSvgPts = (pts: number[][]) => pts.map(p => p.join(',')).join(' ');

  const scorePts = keys.map((key, i) => {
    const val = components[key] ?? '';
    const score = CVSS_VALUE_SCORES[key]?.[val] ?? 0;
    const angle = (2 * Math.PI * i) / n - Math.PI / 2;
    return [cx + r * score * Math.cos(angle), cy + r * score * Math.sin(angle)];
  });

  const rings = [0.25, 0.5, 0.75, 1.0];

  const labelPts = keys.map((key, i) => {
    const angle = (2 * Math.PI * i) / n - Math.PI / 2;
    const dist = r + 16;
    return {
      key,
      x: cx + dist * Math.cos(angle),
      y: cy + dist * Math.sin(angle),
    };
  });

  return (
    <svg viewBox="0 0 160 160" className="w-full max-w-[180px] mx-auto" aria-label="CVSS radar chart">
      {rings.map((scale) => (
        <polygon
          key={scale}
          points={toSvgPts(points(scale))}
          fill="none"
          stroke="var(--border)"
          strokeWidth={scale === 1.0 ? 1 : 0.5}
        />
      ))}
      {points(1.0).map(([x, y], i) => (
        <line key={i} x1={cx} y1={cy} x2={x} y2={y} stroke="var(--border)" strokeWidth={0.5} />
      ))}
      <polygon
        points={toSvgPts(scorePts)}
        fill="color-mix(in srgb, var(--accent-blue) 25%, transparent)"
        stroke="var(--accent-blue)"
        strokeWidth={1.5}
      />
      {scorePts.map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r={2.5} fill="var(--accent-blue)" />
      ))}
      {labelPts.map(({ key, x, y }) => (
        <text
          key={key}
          x={x}
          y={y}
          textAnchor="middle"
          dominantBaseline="middle"
          fontSize={7}
          fill="var(--text-muted)"
        >
          {key}
        </text>
      ))}
    </svg>
  );
}

function CvssGauge({ score, max = 10 }: { score: number; max?: number }) {
  const pct = score / max;
  const radius = 32;
  const cx = 44, cy = 44;
  const sweepDeg = 300;
  const startDeg = -150;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const arcStart = [
    cx + radius * Math.cos(toRad(startDeg)),
    cy + radius * Math.sin(toRad(startDeg)),
  ];
  const endDeg = startDeg + sweepDeg * pct;
  const arcEnd = [
    cx + radius * Math.cos(toRad(endDeg)),
    cy + radius * Math.sin(toRad(endDeg)),
  ];
  const largeArc = sweepDeg * pct > 180 ? 1 : 0;
  const bgEndDeg = startDeg + sweepDeg;
  const bgEnd = [
    cx + radius * Math.cos(toRad(bgEndDeg)),
    cy + radius * Math.sin(toRad(bgEndDeg)),
  ];

  const color = score >= 9
    ? 'var(--accent-red)'
    : score >= 7
      ? 'var(--accent-orange, #f97316)'
      : score >= 4
        ? 'var(--accent-yellow, #eab308)'
        : 'var(--accent-green, #22c55e)';

  return (
    <svg viewBox="0 0 88 60" className="w-[88px] h-[60px]" aria-label={`CVSS score ${score}`}>
      <path
        d={`M ${arcStart[0]} ${arcStart[1]} A ${radius} ${radius} 0 1 1 ${bgEnd[0]} ${bgEnd[1]}`}
        fill="none" stroke="var(--border)" strokeWidth={5} strokeLinecap="round"
      />
      {pct > 0 && (
        <path
          d={`M ${arcStart[0]} ${arcStart[1]} A ${radius} ${radius} 0 ${largeArc} 1 ${arcEnd[0]} ${arcEnd[1]}`}
          fill="none" stroke={color} strokeWidth={5} strokeLinecap="round"
        />
      )}
      <text x={cx} y={cy - 2} textAnchor="middle" dominantBaseline="middle" fontSize={13} fontWeight="700" fill={color}>
        {score.toFixed(1)}
      </text>
      <text x={cx} y={cy + 11} textAnchor="middle" fontSize={6} fill="var(--text-muted)">/ {max}</text>
    </svg>
  );
}

// ---------------------------------------------------------------------------
// CveDetailDialog — exported
// ---------------------------------------------------------------------------

export function CveDetailDialog({ cveId, onClose }: { readonly cveId: string; readonly onClose: () => void }) {
  const [detail, setDetail] = React.useState<CveDetail | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    setLoading(true);
    setError(null);
    fetch(`/api/proxy/patch/cve/${encodeURIComponent(cveId)}`)
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(d => { setDetail(d); setLoading(false); })
      .catch(() => { setError('Failed to load CVE details'); setLoading(false); });
  }, [cveId]);

  const cvssComponents = React.useMemo(
    () => detail?.vectorString ? parseCvssVector(detail.vectorString) : {},
    [detail?.vectorString]
  );

  const baseScore = detail?.baseScore ? parseFloat(detail.baseScore) : null;
  const temporalScore = detail?.temporalScore ? parseFloat(detail.temporalScore) : null;

  return (
    <Dialog open onOpenChange={open => { if (!open) onClose(); }}>
      <DialogContent className="max-w-xl" style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border)' }}>
        <DialogHeader>
          <DialogTitle className="font-mono text-sm" style={{ color: 'var(--accent-blue)' }}>{cveId}</DialogTitle>
        </DialogHeader>
        {loading && (
          <div className="space-y-2 py-2">
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-4 w-1/2" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-16 w-full" />
          </div>
        )}
        {error && <p className="text-sm py-2" style={{ color: 'var(--accent-red)' }}>{error}</p>}
        {detail && (
          <ScrollArea className="max-h-[70vh]">
            <div className="space-y-4 text-sm pr-1">
              {/* Title + severity badges */}
              <div>
                <p className="font-medium mb-2" style={{ color: 'var(--text-primary)' }}>{detail.cveTitle}</p>
                <div className="flex flex-wrap gap-2">
                  <Badge className="text-[11px]" style={{
                    background: `color-mix(in srgb, ${severityColor(detail.severity)} 15%, transparent)`,
                    color: severityColor(detail.severity),
                    borderColor: `color-mix(in srgb, ${severityColor(detail.severity)} 35%, transparent)`,
                    border: '1px solid',
                  }}>
                    {detail.severity}
                  </Badge>
                  {detail.impact && (
                    <Badge variant="outline" className="text-[11px]" style={{ color: 'var(--text-secondary)', borderColor: 'var(--border)' }}>
                      {detail.impact}
                    </Badge>
                  )}
                  {detail.vulnType && (
                    <Badge variant="outline" className="text-[11px]" style={{ color: 'var(--text-secondary)', borderColor: 'var(--border)' }}>
                      {detail.vulnType}
                    </Badge>
                  )}
                </div>
              </div>

              {/* CVSS scores section */}
              {(baseScore !== null || temporalScore !== null) && (
                <div className="rounded-lg border p-3 space-y-3" style={{ borderColor: 'var(--border)', background: 'var(--bg-subtle)' }}>
                  <p className="text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--text-muted)' }}>CVSS Scores</p>

                  <div className="flex gap-4 items-end">
                    {baseScore !== null && (
                      <div className="flex flex-col items-center gap-0.5">
                        <CvssGauge score={baseScore} />
                        <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>Base Score</span>
                      </div>
                    )}
                    {temporalScore !== null && (
                      <div className="flex flex-col items-center gap-0.5">
                        <CvssGauge score={temporalScore} />
                        <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>Temporal Score</span>
                      </div>
                    )}
                    {detail.vectorString && Object.keys(cvssComponents).length > 0 && (
                      <div className="flex-1">
                        <CvssRadar components={cvssComponents} />
                      </div>
                    )}
                  </div>

                  {detail.vectorString && (
                    <p className="font-mono text-[10px] break-all" style={{ color: 'var(--text-muted)' }}>
                      {detail.vectorString}
                    </p>
                  )}

                  {Object.keys(cvssComponents).length > 0 && (
                    <div className="space-y-1.5 pt-1">
                      <p className="text-[10px] font-semibold uppercase tracking-wide mb-1" style={{ color: 'var(--text-muted)' }}>Vector Components</p>
                      {(Object.keys(CVSS_LABELS) as (keyof CvssComponents)[]).map((key) => {
                        const val = cvssComponents[key];
                        if (!val) return null;
                        const score = CVSS_VALUE_SCORES[key]?.[val] ?? 0;
                        const label = CVSS_VALUE_LABELS[key]?.[val] ?? val;
                        return (
                          <CvssBar
                            key={key}
                            label={CVSS_LABELS[key]}
                            value={label}
                            score={score}
                          />
                        );
                      })}
                    </div>
                  )}
                </div>
              )}

              {/* Description */}
              {detail.description && (
                <p className="text-xs leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                  {detail.description}
                </p>
              )}

              {/* Metadata grid */}
              <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs rounded-lg border p-3" style={{ borderColor: 'var(--border)', background: 'var(--bg-subtle)' }}>
                <span style={{ color: 'var(--text-muted)' }}>Exploited</span>
                <span style={{ color: detail.exploited === 'Yes' ? 'var(--accent-red)' : 'var(--text-secondary)', fontWeight: detail.exploited === 'Yes' ? 600 : undefined }}>
                  {detail.exploited || '—'}
                </span>
                <span style={{ color: 'var(--text-muted)' }}>Publicly Disclosed</span>
                <span style={{ color: 'var(--text-secondary)' }}>{detail.publiclyDisclosed || '—'}</span>
                <span style={{ color: 'var(--text-muted)' }}>Exploitability</span>
                <span style={{ color: 'var(--text-secondary)' }}>{detail.latestSoftwareRelease || '—'}</span>
                {detail.releaseDate && (
                  <>
                    <span style={{ color: 'var(--text-muted)' }}>Release Date</span>
                    <span style={{ color: 'var(--text-secondary)' }}>{detail.releaseDate.split('T')[0]}</span>
                  </>
                )}
                {detail.tag && (
                  <>
                    <span style={{ color: 'var(--text-muted)' }}>Tag</span>
                    <span style={{ color: 'var(--text-secondary)' }}>{detail.tag}</span>
                  </>
                )}
              </div>

              {/* MITRE link */}
              {detail.mitreUrl && (
                <a href={detail.mitreUrl} target="_blank" rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-xs"
                  style={{ color: 'var(--accent-blue)' }}>
                  View on MITRE <ExternalLink className="h-3 w-3" />
                </a>
              )}
            </div>
          </ScrollArea>
        )}
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// CveBadges — exported
// Self-contained: manages expand/collapse + opens CveDetailDialog on click
// ---------------------------------------------------------------------------

const MAX_VISIBLE_CVES = 3;

export function CveBadges({ cves }: { readonly cves: readonly string[] }) {
  const [expanded, setExpanded] = React.useState(false);
  const [selectedCve, setSelectedCve] = React.useState<string | null>(null);

  if (cves.length === 0) return <span style={{ color: 'var(--text-muted)' }}>&mdash;</span>;

  const visible = expanded ? cves : cves.slice(0, MAX_VISIBLE_CVES);
  const overflow = cves.length - MAX_VISIBLE_CVES;

  return (
    <>
      {selectedCve && <CveDetailDialog cveId={selectedCve} onClose={() => setSelectedCve(null)} />}
      <div className="flex flex-wrap gap-1 items-center">
        {visible.map((cve) => (
          <button
            key={cve}
            onClick={(e) => { e.stopPropagation(); setSelectedCve(cve); }}
            className="font-mono text-[10px] px-1.5 py-0.5 rounded-sm border transition-colors hover:opacity-80 cursor-pointer"
            style={{
              color: 'var(--accent-blue)',
              borderColor: 'color-mix(in srgb, var(--accent-blue) 35%, transparent)',
              background: 'color-mix(in srgb, var(--accent-blue) 10%, transparent)',
            }}
          >
            {cve}
          </button>
        ))}
        {!expanded && overflow > 0 && (
          <button
            onClick={(e) => { e.stopPropagation(); setExpanded(true); }}
            className="inline-flex items-center gap-0.5 text-[10px] px-1.5 py-0.5 rounded-sm border transition-colors hover:opacity-80"
            style={{ color: 'var(--text-muted)', borderColor: 'var(--border)' }}
          >
            +{overflow} more <ChevronDown className="h-2.5 w-2.5" />
          </button>
        )}
        {expanded && overflow > 0 && (
          <button
            onClick={(e) => { e.stopPropagation(); setExpanded(false); }}
            className="inline-flex items-center gap-0.5 text-[10px] px-1.5 py-0.5 rounded-sm border transition-colors hover:opacity-80"
            style={{ color: 'var(--text-muted)', borderColor: 'var(--border)' }}
          >
            Show less <ChevronUp className="h-2.5 w-2.5" />
          </button>
        )}
      </div>
    </>
  );
}
