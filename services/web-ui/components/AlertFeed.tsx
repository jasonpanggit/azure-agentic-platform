'use client';

import React, { useState, useEffect, useCallback } from 'react';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Skeleton } from '@/components/ui/skeleton';
import { Bell } from 'lucide-react';
import { useAppState } from '@/lib/app-state-context';

interface Incident {
  incident_id: string;
  severity: string;
  domain: string;
  status: string;
  created_at: string;
  title?: string;
  resource_id?: string;
  resource_name?: string;
  resource_group?: string;
  resource_type?: string;
  subscription_id?: string;
  investigation_status?: string;
  evidence_collected_at?: string;
}

interface AlertFeedProps {
  subscriptions: string[];
  filters: {
    severity?: string;
    domain?: string;
    status?: string;
  };
}

const POLL_INTERVAL_MS = 5000;

function getSeverityColor(severity: string): string {
  const s = (severity ?? '').toLowerCase()
  if (s.includes('sev0') || s.includes('critical')) return 'var(--accent-red)'
  if (s.includes('sev1') || s.includes('high')) return 'var(--accent-orange)'
  if (s.includes('sev2') || s.includes('medium')) return 'var(--accent-yellow)'
  if (s.includes('sev3') || s.includes('low')) return 'var(--accent-purple)'
  return 'var(--text-muted)'
}

function formatRelativeTime(isoString: string): string {
  const diffMs = Date.now() - new Date(isoString).getTime()
  const mins = Math.floor(diffMs / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

export function AlertFeed({ subscriptions, filters }: AlertFeedProps) {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { setAlertCount } = useAppState();

  const fetchIncidents = useCallback(async () => {
    setError(null);
    try {
      const params = new URLSearchParams();
      if (subscriptions.length > 0) {
        params.set('subscription', subscriptions.join(','));
      }
      if (filters.severity && filters.severity !== 'all') params.set('severity', filters.severity);
      if (filters.domain && filters.domain !== 'all') params.set('domain', filters.domain);
      if (filters.status && filters.status !== 'all') params.set('status', filters.status);

      const res = await fetch(`/api/proxy/incidents?${params.toString()}`);
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data)) {
          setIncidents(data);
        } else {
          setError('Unexpected response format from server');
        }
      } else {
        setError(`Failed to fetch alerts: ${res.status}`);
      }
    } catch {
      // Polling failure — retry on next interval
    } finally {
      setLoading(false);
    }
  }, [subscriptions, filters.severity, filters.domain, filters.status]);

  useEffect(() => {
    fetchIncidents();
    const interval = setInterval(fetchIncidents, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [fetchIncidents]);

  useEffect(() => {
    setAlertCount(incidents.length);
  }, [incidents.length, setAlertCount]);

  if (loading) {
    return (
      <div className="rounded-md border overflow-hidden">
        <Table className="w-full text-sm">
          <TableHeader>
            <TableRow>
              <TableHead className="h-10 px-3 text-left font-semibold" style={{ color: 'var(--text-muted)' }}>Severity</TableHead>
              <TableHead className="h-10 px-3 text-left font-semibold" style={{ color: 'var(--text-muted)' }}>Domain</TableHead>
              <TableHead className="h-10 px-3 text-left font-semibold" style={{ color: 'var(--text-muted)' }}>Resource</TableHead>
              <TableHead className="h-10 px-3 text-left font-semibold" style={{ color: 'var(--text-muted)' }}>Resource Group</TableHead>
              <TableHead className="h-10 px-3 text-left font-semibold" style={{ color: 'var(--text-muted)' }}>Status</TableHead>
              <TableHead className="h-10 px-3 text-left font-semibold" style={{ color: 'var(--text-muted)' }}>Investigation</TableHead>
              <TableHead className="h-10 px-3 text-left font-semibold" style={{ color: 'var(--text-muted)' }}>Time</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {Array.from({ length: 4 }).map((_, i) => (
              <TableRow key={i} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                <TableCell className="py-3 pr-2" style={{ borderLeft: '4px solid var(--bg-subtle)', paddingLeft: '12px' }}>
                  <Skeleton className="h-4 w-14" />
                </TableCell>
                <TableCell className="py-3 px-2"><Skeleton className="h-4 w-16" /></TableCell>
                <TableCell className="py-3 px-2"><Skeleton className="h-4 w-32" /></TableCell>
                <TableCell className="py-3 px-2"><Skeleton className="h-4 w-24" /></TableCell>
                <TableCell className="py-3 px-2"><Skeleton className="h-4 w-14" /></TableCell>
                <TableCell className="py-3 px-2"><Skeleton className="h-4 w-20" /></TableCell>
                <TableCell className="py-3 px-2"><Skeleton className="h-4 w-10" /></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center gap-2 px-4 py-6 text-sm" style={{ color: 'var(--accent-red)' }}>
        <span>⚠</span>
        <span>{error}</span>
      </div>
    );
  }

  if (incidents.length === 0 && !error) {
    return (
      <div className="flex flex-col items-center justify-center py-16 gap-3">
        <Bell className="h-8 w-8" style={{ color: 'var(--text-muted)' }} />
        <p className="font-semibold text-base" style={{ color: 'var(--text-primary)' }}>No alerts</p>
        <p className="text-sm text-center" style={{ color: 'var(--text-muted)' }}>
          No alerts match your current filters. Adjust the filters above or check back later.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-md border overflow-hidden">
      <Table className="w-full text-sm">
        <TableHeader>
          <TableRow>
            <TableHead className="h-10 px-3 text-left font-semibold" style={{ color: 'var(--text-muted)' }}>Severity</TableHead>
            <TableHead className="h-10 px-3 text-left font-semibold" style={{ color: 'var(--text-muted)' }}>Domain</TableHead>
            <TableHead className="h-10 px-3 text-left font-semibold" style={{ color: 'var(--text-muted)' }}>Resource</TableHead>
            <TableHead className="h-10 px-3 text-left font-semibold" style={{ color: 'var(--text-muted)' }}>Resource Group</TableHead>
            <TableHead className="h-10 px-3 text-left font-semibold" style={{ color: 'var(--text-muted)' }}>Status</TableHead>
            <TableHead className="h-10 px-3 text-left font-semibold" style={{ color: 'var(--text-muted)' }}>Investigation</TableHead>
            <TableHead className="h-10 px-3 text-left font-semibold" style={{ color: 'var(--text-muted)' }}>Time</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {incidents.map((incident) => (
            <TableRow
              key={incident.incident_id}
              className="transition-colors cursor-pointer"
              style={{ borderBottom: '1px solid var(--border-subtle)' }}
              onMouseEnter={(e) => { (e.currentTarget as HTMLTableRowElement).style.background = 'var(--bg-subtle)' }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLTableRowElement).style.background = 'transparent' }}
            >
              <TableCell className="py-3 pr-2" style={{ borderLeft: `4px solid ${getSeverityColor(incident.severity)}`, paddingLeft: '12px' }}>
                <div className="flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: getSeverityColor(incident.severity) }} />
                  <span className="text-[11px] font-medium" style={{ color: getSeverityColor(incident.severity) }}>
                    {incident.severity}
                  </span>
                </div>
              </TableCell>
              <TableCell className="py-3 px-2">
                <span className="text-[11px] px-2 py-0.5 rounded font-medium" style={{ background: 'var(--bg-subtle)', color: 'var(--text-secondary)' }}>
                  {incident.domain}
                </span>
              </TableCell>
              <TableCell className="py-3 px-2 max-w-[180px]">
                {incident.resource_name ? (
                  <span
                    className="font-mono text-xs truncate block"
                    style={{ color: 'var(--text-secondary)' }}
                    title={incident.resource_name}
                  >
                    {incident.resource_name.length > 20
                      ? incident.resource_name.slice(0, 20) + '…'
                      : incident.resource_name}
                  </span>
                ) : (
                  <span className="text-[12px] font-semibold font-mono truncate block" style={{ color: 'var(--text-primary)' }}>
                    {incident.title || incident.resource_id || incident.incident_id}
                  </span>
                )}
              </TableCell>
              <TableCell className="py-3 px-2">
                <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                  {incident.resource_group ?? '—'}
                </span>
              </TableCell>
              <TableCell className="py-3 px-2">
                <span className="text-[11px] px-2 py-0.5 rounded" style={{ background: 'var(--bg-subtle)', color: 'var(--text-secondary)' }}>
                  {incident.status}
                </span>
              </TableCell>
              <TableCell className="py-3 px-2">
                {incident.investigation_status === 'evidence_ready' ? (
                  <span
                    className="text-[11px] px-2 py-0.5 rounded font-medium"
                    style={{ background: 'rgba(34, 197, 94, 0.15)', color: '#16a34a' }}
                  >
                    Evidence Ready
                  </span>
                ) : incident.investigation_status && incident.investigation_status !== 'pending' ? (
                  <span className="text-[11px] px-2 py-0.5 rounded" style={{ background: 'var(--bg-subtle)', color: 'var(--text-muted)' }}>
                    {incident.investigation_status}
                  </span>
                ) : (
                  <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>—</span>
                )}
              </TableCell>
              <TableCell className="py-3 px-2 text-right">
                <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
                  {formatRelativeTime(incident.created_at)}
                </span>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
