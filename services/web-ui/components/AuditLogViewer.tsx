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
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { FileText } from 'lucide-react';

interface AuditEntry {
  timestamp: string;
  agent: string;
  tool: string;
  outcome: string;
  duration_ms: number;
  properties?: string;
}

interface AuditLogViewerProps {
  incidentId?: string;
}

export function AuditLogViewer({ incidentId }: AuditLogViewerProps) {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [agentFilter, setAgentFilter] = useState('');
  const [actionFilter, setActionFilter] = useState('');
  const [exportLoading, setExportLoading] = useState(false);

  const fetchAuditLog = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (incidentId) params.set('incident_id', incidentId);
      if (agentFilter) params.set('agent', agentFilter);
      if (actionFilter) params.set('action', actionFilter);

      const res = await fetch(`/api/proxy/audit?${params.toString()}`);
      if (res.ok) {
        setEntries(await res.json());
      }
    } catch {
      // Query failure
    } finally {
      setLoading(false);
    }
  }, [incidentId, agentFilter, actionFilter]);

  const handleExport = useCallback(async () => {
    setExportLoading(true);
    try {
      const now = new Date();
      const thirtyDaysAgo = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
      const params = new URLSearchParams({
        from_time: thirtyDaysAgo.toISOString(),
        to_time: now.toISOString(),
      });
      const res = await fetch(`/api/proxy/audit/export?${params.toString()}`);
      if (!res.ok) throw new Error(`Export failed: ${res.status}`);
      const data = await res.json();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `remediation-report-${thirtyDaysAgo.toISOString().slice(0, 10)}-${now.toISOString().slice(0, 10)}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Export failed:', err);
    } finally {
      setExportLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAuditLog();
  }, [fetchAuditLog]);

  if (entries.length === 0 && !loading) {
    return (
      <div className="flex flex-col items-center justify-center py-16 gap-3">
        <p className="font-semibold text-base">No actions recorded</p>
        <p className="text-sm text-muted-foreground text-center">
          Agent actions for this time range will appear here once incidents are triaged.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 h-full">
      <div className="flex gap-2 flex-wrap items-center">
        <Select
          value={agentFilter}
          onValueChange={(value) => setAgentFilter(value)}
        >
          <SelectTrigger className="w-[140px]">
            <SelectValue placeholder="All Agents" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="">All Agents</SelectItem>
            <SelectItem value="compute">Compute</SelectItem>
            <SelectItem value="network">Network</SelectItem>
            <SelectItem value="storage">Storage</SelectItem>
            <SelectItem value="security">Security</SelectItem>
            <SelectItem value="arc">Arc</SelectItem>
            <SelectItem value="sre">SRE</SelectItem>
          </SelectContent>
        </Select>

        <Input
          className="w-[200px]"
          placeholder="Filter by action..."
          value={actionFilter}
          onChange={(e) => setActionFilter(e.target.value)}
        />

        <Button
          variant="outline"
          size="sm"
          onClick={handleExport}
          disabled={exportLoading}
        >
          <FileText className="h-4 w-4 mr-1.5" />
          {exportLoading ? 'Exporting...' : 'Export Report'}
        </Button>
      </div>

      {loading ? (
        <div className="flex flex-col gap-1">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      ) : (
        <div className="rounded-md border overflow-hidden">
          <Table className="w-full text-sm">
            <TableHeader>
              <TableRow>
                <TableHead className="h-10 px-3 text-left font-semibold text-muted-foreground">Timestamp</TableHead>
                <TableHead className="h-10 px-3 text-left font-semibold text-muted-foreground">Agent</TableHead>
                <TableHead className="h-10 px-3 text-left font-semibold text-muted-foreground">Tool</TableHead>
                <TableHead className="h-10 px-3 text-left font-semibold text-muted-foreground">Outcome</TableHead>
                <TableHead className="h-10 px-3 text-left font-semibold text-muted-foreground">Duration</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {entries.map((item, idx) => (
                <TableRow key={idx} className="border-b hover:bg-muted/30 transition-colors">
                  <TableCell className="h-10 px-3 align-middle">
                    {new Date(item.timestamp).toLocaleString()}
                  </TableCell>
                  <TableCell className="h-10 px-3 align-middle">{item.agent}</TableCell>
                  <TableCell className="h-10 px-3 align-middle">{item.tool}</TableCell>
                  <TableCell className="h-10 px-3 align-middle">
                    <Badge
                      variant={
                        item.outcome === '200' || item.outcome === 'success'
                          ? 'default'
                          : 'destructive'
                      }
                    >
                      {item.outcome}
                    </Badge>
                  </TableCell>
                  <TableCell className="h-10 px-3 align-middle">{item.duration_ms}ms</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
