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
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Bell } from 'lucide-react';

interface Incident {
  incident_id: string;
  severity: string;
  domain: string;
  status: string;
  created_at: string;
  title?: string;
  resource_id?: string;
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

function SeverityBadge({ severity }: { severity: string }) {
  const isCritical = severity === 'Sev0' || severity === 'Sev1';
  return (
    <Badge variant={isCritical ? 'destructive' : 'outline'}>
      {severity}
    </Badge>
  );
}

export function AlertFeed({ subscriptions, filters }: AlertFeedProps) {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchIncidents = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (subscriptions.length > 0) {
        params.set('subscription', subscriptions.join(','));
      }
      if (filters.severity) params.set('severity', filters.severity);
      if (filters.domain) params.set('domain', filters.domain);
      if (filters.status) params.set('status', filters.status);

      const res = await fetch(`/api/proxy/incidents?${params.toString()}`);
      if (res.ok) {
        const data = await res.json();
        setIncidents(data);
      }
    } catch {
      // Polling failure — retry on next interval
    } finally {
      setLoading(false);
    }
  }, [subscriptions, filters]);

  useEffect(() => {
    fetchIncidents();
    const interval = setInterval(fetchIncidents, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [fetchIncidents]);

  if (loading) {
    return (
      <div className="flex flex-col gap-1">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    );
  }

  if (incidents.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 gap-3">
        <Bell className="h-8 w-8 text-muted-foreground" />
        <p className="font-semibold text-base">No alerts</p>
        <p className="text-sm text-muted-foreground text-center">
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
            <TableHead className="h-10 px-3 text-left font-semibold text-muted-foreground">Severity</TableHead>
            <TableHead className="h-10 px-3 text-left font-semibold text-muted-foreground">Domain</TableHead>
            <TableHead className="h-10 px-3 text-left font-semibold text-muted-foreground">Resource</TableHead>
            <TableHead className="h-10 px-3 text-left font-semibold text-muted-foreground">Status</TableHead>
            <TableHead className="h-10 px-3 text-left font-semibold text-muted-foreground">Time</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {incidents.map((item) => (
            <TableRow key={item.incident_id} className="border-b hover:bg-muted/30 transition-colors">
              <TableCell className="h-10 px-3 align-middle">
                <SeverityBadge severity={item.severity} />
              </TableCell>
              <TableCell className="h-10 px-3 align-middle">{item.domain}</TableCell>
              <TableCell className="h-10 px-3 align-middle truncate max-w-[200px]">
                {item.title || item.resource_id || item.incident_id}
              </TableCell>
              <TableCell className="h-10 px-3 align-middle">
                <Badge variant="outline">{item.status}</Badge>
              </TableCell>
              <TableCell className="h-10 px-3 align-middle">
                {new Date(item.created_at).toLocaleTimeString()}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
