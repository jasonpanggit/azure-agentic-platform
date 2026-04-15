'use client'

import React, { useEffect, useState, useCallback } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Alert, AlertDescription } from '@/components/ui/alert'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'
import {
  BarChart2,
  RefreshCw,
  FileText,
  CheckCircle2,
  XCircle,
  HelpCircle,
} from 'lucide-react'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ResourceAttainment {
  resource_id: string
  availability_pct: number | null
  downtime_minutes: number | null
  data_source: string
}

interface SLAComplianceResult {
  sla_id: string
  sla_name: string
  target_availability_pct: number
  attained_availability_pct: number | null
  is_compliant: boolean | null
  measurement_period: string
  period_start: string
  period_end: string
  resource_attainments: ResourceAttainment[]
  data_source: string
  duration_ms: number
}

interface SLAComplianceResponse {
  results: SLAComplianceResult[]
  computed_at: string
  error?: string
}

interface SLATabProps {
  subscriptions: string[]
}

// ---------------------------------------------------------------------------
// SVG radial gauge
// ---------------------------------------------------------------------------

function AttainmentGauge({
  attained,
  target,
}: {
  attained: number | null
  target: number
}) {
  const size = 120
  const strokeWidth = 10
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  const pct = attained ?? 0
  const dashOffset = circumference - (pct / 100) * circumference
  const color =
    attained === null
      ? 'var(--text-muted)'
      : attained >= target
        ? 'var(--accent-green)'
        : 'var(--accent-red)'

  return (
    <div className="flex flex-col items-center">
      <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--border)"
          strokeWidth={strokeWidth}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeDasharray={circumference}
          strokeDashoffset={dashOffset}
          strokeLinecap="round"
          style={{ transition: 'stroke-dashoffset 0.6s ease' }}
        />
      </svg>
      <span
        className="text-lg font-semibold mt-1"
        style={{ color: 'var(--text-primary)' }}
      >
        {attained !== null ? `${attained.toFixed(3)}%` : 'N/A'}
      </span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Compliance badge
// ---------------------------------------------------------------------------

function ComplianceBadge({ isCompliant }: { isCompliant: boolean | null }) {
  if (isCompliant === null) {
    return (
      <Badge
        style={{
          background: 'color-mix(in srgb, var(--text-muted) 15%, transparent)',
          color: 'var(--text-muted)',
          border: '1px solid var(--border)',
        }}
      >
        <HelpCircle className="h-3 w-3 mr-1" /> No data
      </Badge>
    )
  }
  return isCompliant ? (
    <Badge
      style={{
        background: 'color-mix(in srgb, var(--accent-green) 15%, transparent)',
        color: 'var(--accent-green)',
        border: '1px solid color-mix(in srgb, var(--accent-green) 30%, transparent)',
      }}
    >
      <CheckCircle2 className="h-3 w-3 mr-1" /> Compliant
    </Badge>
  ) : (
    <Badge
      style={{
        background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
        color: 'var(--accent-red)',
        border: '1px solid color-mix(in srgb, var(--accent-red) 30%, transparent)',
      }}
    >
      <XCircle className="h-3 w-3 mr-1" /> Breach
    </Badge>
  )
}

// ---------------------------------------------------------------------------
// Stub 12-month trend data
// ---------------------------------------------------------------------------

interface TrendEntry {
  month: string
  attained: number
}

function buildTrendData(target: number): TrendEntry[] {
  return [
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
  ].map((month) => ({
    month,
    attained: Number((target - 0.02 + Math.random() * 0.04).toFixed(3)),
  }))
}

// ---------------------------------------------------------------------------
// SLA card
// ---------------------------------------------------------------------------

interface SLACardProps {
  result: SLAComplianceResult
  onTriggerReport: () => void
  reportLoading: boolean
  reportMessage: string
}

function SLACard({
  result,
  onTriggerReport,
  reportLoading,
  reportMessage,
}: SLACardProps) {
  const trendData = buildTrendData(result.target_availability_pct)

  return (
    <Card style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-2">
          <CardTitle
            className="text-sm font-semibold truncate"
            style={{ color: 'var(--text-primary)' }}
          >
            {result.sla_name}
          </CardTitle>
          <ComplianceBadge isCompliant={result.is_compliant} />
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Gauge */}
        <div className="flex justify-center">
          <AttainmentGauge
            attained={result.attained_availability_pct}
            target={result.target_availability_pct}
          />
        </div>

        {/* Metrics row */}
        <div
          className="flex justify-between text-xs"
          style={{ color: 'var(--text-secondary)' }}
        >
          <span>
            Target:{' '}
            <strong style={{ color: 'var(--text-primary)' }}>
              {result.target_availability_pct.toFixed(3)}%
            </strong>
          </span>
          <span>
            Period:{' '}
            <strong style={{ color: 'var(--text-primary)' }}>
              {result.period_start?.slice(0, 7) ?? '—'}
            </strong>
          </span>
        </div>

        {/* Resource breakdown table */}
        {result.resource_attainments.length > 0 && (
          <div
            className="rounded overflow-hidden"
            style={{ border: '1px solid var(--border)' }}
          >
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead style={{ color: 'var(--text-secondary)', fontSize: '11px' }}>
                    Resource
                  </TableHead>
                  <TableHead style={{ color: 'var(--text-secondary)', fontSize: '11px' }}>
                    Availability
                  </TableHead>
                  <TableHead style={{ color: 'var(--text-secondary)', fontSize: '11px' }}>
                    Downtime
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {result.resource_attainments.map((ra) => (
                  <TableRow key={ra.resource_id}>
                    <TableCell
                      className="font-mono text-xs truncate max-w-[120px]"
                      style={{ color: 'var(--text-primary)' }}
                    >
                      {ra.resource_id.split('/').pop() ?? ra.resource_id}
                    </TableCell>
                    <TableCell
                      className="text-xs"
                      style={{ color: 'var(--text-primary)' }}
                    >
                      {ra.availability_pct != null
                        ? `${ra.availability_pct.toFixed(2)}%`
                        : 'N/A'}
                    </TableCell>
                    <TableCell
                      className="text-xs"
                      style={{ color: 'var(--text-secondary)' }}
                    >
                      {ra.downtime_minutes != null
                        ? `${ra.downtime_minutes.toFixed(0)} min`
                        : '—'}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}

        {/* 12-month trend sparkline */}
        <div>
          <p className="text-xs mb-1" style={{ color: 'var(--text-muted)' }}>
            12-month trend (stub — historical data available after 12 months)
          </p>
          <ResponsiveContainer width="100%" height={80}>
            <BarChart
              data={trendData}
              margin={{ top: 0, right: 0, bottom: 0, left: 0 }}
            >
              <XAxis
                dataKey="month"
                tick={{ fontSize: 9, fill: 'var(--text-muted)' }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                domain={[Math.max(99, result.target_availability_pct - 0.5), 100]}
                hide
              />
              <Tooltip
                contentStyle={{
                  background: 'var(--bg-surface)',
                  border: '1px solid var(--border)',
                  fontSize: 11,
                }}
                labelStyle={{ color: 'var(--text-primary)' }}
                itemStyle={{ color: 'var(--accent-blue)' }}
              />
              <Bar
                dataKey="attained"
                fill="var(--accent-blue)"
                radius={[2, 2, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Report trigger */}
        <div className="space-y-1">
          <Button
            size="sm"
            variant="outline"
            onClick={onTriggerReport}
            disabled={reportLoading}
            className="w-full text-xs"
            style={{ borderColor: 'var(--border)', color: 'var(--text-primary)' }}
          >
            <FileText className="h-3 w-3 mr-1" />
            {reportLoading ? 'Generating…' : 'Generate Report'}
          </Button>
          {reportMessage && (
            <p className="text-xs text-center" style={{ color: 'var(--text-muted)' }}>
              {reportMessage}
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

function EmptyState({ message }: { message: string }) {
  return (
    <div
      className="col-span-full flex flex-col items-center py-16"
      style={{ color: 'var(--text-muted)' }}
    >
      <BarChart2 className="h-12 w-12 mb-3 opacity-30" />
      <p>{message}</p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// SLATab
// ---------------------------------------------------------------------------

export function SLATab({ subscriptions: _subscriptions }: SLATabProps) {
  const [compliance, setCompliance] = useState<SLAComplianceResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reportLoading, setReportLoading] = useState<Record<string, boolean>>({})
  const [reportMessage, setReportMessage] = useState<Record<string, string>>({})

  const fetchCompliance = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/proxy/sla/compliance')
      const data: SLAComplianceResponse = await res.json()
      if (data.error && !data.results?.length) {
        setError(data.error)
      }
      setCompliance(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load SLA compliance')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchCompliance()
  }, [fetchCompliance])

  async function triggerReport(slaId: string) {
    setReportLoading((prev) => ({ ...prev, [slaId]: true }))
    setReportMessage((prev) => ({ ...prev, [slaId]: '' }))
    try {
      const res = await fetch(`/api/proxy/sla/report/${slaId}`, { method: 'POST' })
      const data: unknown = await res.json()
      if (!res.ok) {
        setReportMessage((prev) => ({
          ...prev,
          [slaId]: (data as { error?: string }).error ?? 'Report failed',
        }))
      } else {
        setReportMessage((prev) => ({
          ...prev,
          [slaId]: `Report sent to ${(data as { emailed_to?: string[] }).emailed_to?.length ?? 0} recipients`,
        }))
      }
    } catch (err) {
      setReportMessage((prev) => ({
        ...prev,
        [slaId]: err instanceof Error ? err.message : 'Report failed',
      }))
    } finally {
      setReportLoading((prev) => ({ ...prev, [slaId]: false }))
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2
            className="text-lg font-semibold"
            style={{ color: 'var(--text-primary)' }}
          >
            SLA Compliance
          </h2>
          <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
            Current-period attainment against SLA targets
          </p>
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={fetchCompliance}
          disabled={loading}
          style={{ borderColor: 'var(--border)', color: 'var(--text-primary)' }}
        >
          <RefreshCw className={`h-4 w-4 mr-1 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {error && (
        <Alert
          style={{
            borderColor: 'var(--accent-red)',
            background: 'color-mix(in srgb, var(--accent-red) 10%, transparent)',
          }}
        >
          <AlertDescription style={{ color: 'var(--accent-red)' }}>
            {error}
          </AlertDescription>
        </Alert>
      )}

      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-64 rounded-lg" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {compliance?.results.map((result) => (
            <SLACard
              key={result.sla_id}
              result={result}
              onTriggerReport={() => triggerReport(result.sla_id)}
              reportLoading={reportLoading[result.sla_id] ?? false}
              reportMessage={reportMessage[result.sla_id] ?? ''}
            />
          ))}
          {!compliance?.results?.length && !error && (
            <EmptyState message="No SLA definitions found. Create one via the admin API." />
          )}
        </div>
      )}
    </div>
  )
}
