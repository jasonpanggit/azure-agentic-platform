'use client'

import { useEffect, useState, useCallback } from 'react'
import { Wrench, RefreshCw, CheckCircle2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

interface MaintenanceEvent {
  event_id: string
  subscription_id: string
  resource_id: string
  resource_group: string
  event_type: string
  title: string
  status: string
  level: string
  impact_start: string
  impact_end: string
  description: string
  severity: string
  detected_at: string
}

interface MaintenanceSummary {
  active_events: number
  planned_upcoming: number
  health_advisories: number
  affected_subscriptions: number
  critical_count: number
}

const REFRESH_INTERVAL_MS = 5 * 60 * 1000 // 5 minutes

function EventTypeBadge({ eventType }: { eventType: string }) {
  const typeMap: Record<string, { label: string; color: string }> = {
    planned_maintenance: { label: 'Planned', color: 'var(--accent-blue)' },
    health_advisory: { label: 'Advisory', color: 'var(--accent-yellow)' },
    resource_degraded: { label: 'Degraded', color: 'var(--accent-red)' },
  }
  const entry = typeMap[eventType] ?? { label: eventType, color: 'var(--accent-blue)' }
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold"
      style={{
        background: `color-mix(in srgb, ${entry.color} 15%, transparent)`,
        color: entry.color,
        border: `1px solid color-mix(in srgb, ${entry.color} 30%, transparent)`,
      }}
    >
      {entry.label}
    </span>
  )
}

function StatusBadge({ status }: { status: string }) {
  const s = status.toLowerCase()
  const color =
    s === 'active' || s === 'inprogress'
      ? 'var(--accent-orange)'
      : s === 'resolved'
      ? 'var(--accent-green)'
      : 'var(--text-secondary)'
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium"
      style={{
        background: `color-mix(in srgb, ${color} 12%, transparent)`,
        color,
        border: `1px solid color-mix(in srgb, ${color} 25%, transparent)`,
      }}
    >
      {status}
    </span>
  )
}

function StatCard({
  label,
  value,
  color,
}: {
  label: string
  value: number
  color?: string
}) {
  return (
    <div
      className="rounded-lg px-4 py-3 flex flex-col gap-0.5 min-w-[130px]"
      style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)' }}
    >
      <span className="text-[22px] font-bold" style={{ color: color ?? 'var(--text-primary)' }}>
        {value}
      </span>
      <span className="text-[11px]" style={{ color: 'var(--text-secondary)' }}>
        {label}
      </span>
    </div>
  )
}

function formatImpactWindow(start: string, end: string): string {
  if (!start) return '—'
  const s = new Date(start)
  if (!end) return s.toLocaleString()
  const e = new Date(end)
  if (s.toDateString() === e.toDateString()) {
    return `${s.toLocaleDateString()} ${s.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} – ${e.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
  }
  return `${s.toLocaleString()} – ${e.toLocaleString()}`
}

export function MaintenanceTab({ subscriptions }: { subscriptions?: string[] }) {
  const [events, setEvents] = useState<MaintenanceEvent[]>([])
  const [summary, setSummary] = useState<MaintenanceSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [eventTypeFilter, setEventTypeFilter] = useState<string>('')
  const [subscriptionFilter, setSubscriptionFilter] = useState<string>('')

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (eventTypeFilter) params.set('event_type', eventTypeFilter)
      if (subscriptionFilter) params.set('subscription_id', subscriptionFilter)
      const qs = params.toString()

      const [eventsRes, summaryRes] = await Promise.all([
        fetch(`/api/proxy/maintenance/events${qs ? `?${qs}` : ''}`),
        fetch('/api/proxy/maintenance/summary'),
      ])

      if (eventsRes.ok) {
        const data = await eventsRes.json()
        setEvents(data.events ?? [])
      }
      if (summaryRes.ok) {
        const data = await summaryRes.json()
        setSummary(data)
      }
    } catch {
      // Silent — stale data remains visible
    } finally {
      setLoading(false)
    }
  }, [eventTypeFilter, subscriptionFilter])

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, REFRESH_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [fetchData])

  async function handleScan() {
    setScanning(true)
    try {
      await fetch('/api/proxy/maintenance/scan', { method: 'POST' })
      await fetchData()
    } finally {
      setScanning(false)
    }
  }

  const allSubscriptions = Array.from(
    new Set([...(subscriptions ?? []), ...events.map((e) => e.subscription_id).filter(Boolean)])
  )

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <Wrench className="h-5 w-5" style={{ color: 'var(--accent-blue)' }} />
          <h2 className="text-[15px] font-semibold" style={{ color: 'var(--text-primary)' }}>
            Maintenance Window Intelligence
          </h2>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <select
            value={eventTypeFilter}
            onChange={(e) => setEventTypeFilter(e.target.value)}
            className="text-[12px] rounded px-2 py-1.5 outline-none"
            style={{
              background: 'var(--bg-subtle)',
              border: '1px solid var(--border)',
              color: 'var(--text-primary)',
            }}
          >
            <option value="">All Types</option>
            <option value="planned_maintenance">Planned Maintenance</option>
            <option value="health_advisory">Health Advisory</option>
            <option value="resource_degraded">Resource Degraded</option>
          </select>
          {allSubscriptions.length > 0 && (
            <select
              value={subscriptionFilter}
              onChange={(e) => setSubscriptionFilter(e.target.value)}
              className="text-[12px] rounded px-2 py-1.5 outline-none"
              style={{
                background: 'var(--bg-subtle)',
                border: '1px solid var(--border)',
                color: 'var(--text-primary)',
              }}
            >
              <option value="">All Subscriptions</option>
              {allSubscriptions.map((s) => (
                <option key={s} value={s}>
                  {s.substring(0, 8)}…
                </option>
              ))}
            </select>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={handleScan}
            disabled={scanning}
            className="gap-1.5 text-[12px]"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${scanning ? 'animate-spin' : ''}`} />
            {scanning ? 'Scanning…' : 'Scan Now'}
          </Button>
        </div>
      </div>

      {/* Summary cards */}
      {summary && (
        <div className="flex flex-wrap gap-3">
          <StatCard label="Active Events" value={summary.active_events} color="var(--accent-orange)" />
          <StatCard label="Planned Maintenance" value={summary.planned_upcoming} color="var(--accent-blue)" />
          <StatCard label="Advisories" value={summary.health_advisories} color="var(--accent-yellow)" />
          <StatCard label="Affected Subscriptions" value={summary.affected_subscriptions} />
          <StatCard label="Critical" value={summary.critical_count} color="var(--accent-red)" />
        </div>
      )}

      {/* Events table */}
      <div
        className="rounded-lg overflow-hidden"
        style={{ border: '1px solid var(--border)', background: 'var(--bg-surface)' }}
      >
        {loading ? (
          <div className="p-8 text-center text-[13px]" style={{ color: 'var(--text-secondary)' }}>
            Loading maintenance events…
          </div>
        ) : events.length === 0 ? (
          <div className="p-10 flex flex-col items-center gap-3" style={{ color: 'var(--text-secondary)' }}>
            <CheckCircle2 className="h-8 w-8" style={{ color: 'var(--accent-green)' }} />
            <p className="text-[14px] font-medium" style={{ color: 'var(--text-primary)' }}>
              No active maintenance events
            </p>
            <p className="text-[13px]">All services operating normally.</p>
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Title</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Impact Window</TableHead>
                <TableHead>Subscription</TableHead>
                <TableHead>Description</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {events.map((event) => (
                <TableRow key={event.event_id}>
                  <TableCell className="font-medium text-[13px] max-w-[200px] truncate">
                    {event.title || '—'}
                  </TableCell>
                  <TableCell>
                    <EventTypeBadge eventType={event.event_type} />
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={event.status} />
                  </TableCell>
                  <TableCell className="text-[12px] whitespace-nowrap" style={{ color: 'var(--text-secondary)' }}>
                    {formatImpactWindow(event.impact_start, event.impact_end)}
                  </TableCell>
                  <TableCell className="text-[12px]" style={{ color: 'var(--text-secondary)' }}>
                    {event.subscription_id ? `${event.subscription_id.substring(0, 8)}…` : '—'}
                  </TableCell>
                  <TableCell
                    className="text-[12px] max-w-[280px]"
                    style={{ color: 'var(--text-secondary)' }}
                    title={event.description}
                  >
                    <span className="line-clamp-2">{event.description || '—'}</span>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
    </div>
  )
}
