'use client'

import React, { useEffect, useState, useCallback } from 'react'
import { Card, CardContent } from '@/components/ui/card'
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
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Legend,
} from 'recharts'
import { Gauge, RefreshCw } from 'lucide-react'
import type {
  TrafficLight,
  CapacityHeadroomResponse,
  IPSpaceHeadroomResponse,
  AKSHeadroomResponse,
  CapacityQuotaItem,
  SubnetHeadroomItem,
  AKSNodePoolHeadroomItem,
} from '@/lib/capacity-types'

// ---------------------------------------------------------------------------
// TrafficBadge — uses CSS semantic tokens only, never hardcoded Tailwind colors
// ---------------------------------------------------------------------------

function TrafficBadge({ light }: { light: TrafficLight }) {
  const styles: Record<TrafficLight, React.CSSProperties> = {
    red: {
      background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
      color: 'var(--accent-red)',
      border: '1px solid color-mix(in srgb, var(--accent-red) 30%, transparent)',
    },
    yellow: {
      background: 'color-mix(in srgb, var(--accent-yellow) 15%, transparent)',
      color: 'var(--accent-yellow)',
      border: '1px solid color-mix(in srgb, var(--accent-yellow) 30%, transparent)',
    },
    green: {
      background: 'color-mix(in srgb, var(--accent-green) 15%, transparent)',
      color: 'var(--accent-green)',
      border: '1px solid color-mix(in srgb, var(--accent-green) 30%, transparent)',
    },
  }
  const labels: Record<TrafficLight, string> = {
    red: 'Critical',
    yellow: 'Warning',
    green: 'Healthy',
  }
  return <Badge style={styles[light]}>{labels[light]}</Badge>
}

// ---------------------------------------------------------------------------
// Summary cards
// ---------------------------------------------------------------------------

interface SummaryCardsProps {
  items: Array<{ traffic_light: TrafficLight }>
}

function SummaryCards({ items }: SummaryCardsProps) {
  const total = items.length
  const critical = items.filter((i) => i.traffic_light === 'red').length
  const warning = items.filter((i) => i.traffic_light === 'yellow').length
  const healthy = items.filter((i) => i.traffic_light === 'green').length

  const cards = [
    { label: 'Total', value: total, color: 'var(--text-primary)' },
    { label: 'Critical', value: critical, color: 'var(--accent-red)' },
    { label: 'Warning', value: warning, color: 'var(--accent-yellow)' },
    { label: 'Healthy', value: healthy, color: 'var(--accent-green)' },
  ]

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      {cards.map(({ label, value, color }) => (
        <Card key={label} style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
          <CardContent className="pt-4 pb-3">
            <p className="text-xs mb-1" style={{ color: 'var(--text-muted)' }}>{label}</p>
            <p className="text-2xl font-bold" style={{ color }}>{value}</p>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// 90-day forecast chart (only rendered when snapshot_count >= 3)
// ---------------------------------------------------------------------------

interface ForecastPoint {
  day: string
  usage_pct: number
  projected: boolean
}

function buildForecastData(item: CapacityQuotaItem): ForecastPoint[] {
  // Simulate historical + projected 90-day data from current snapshot
  const today = new Date()
  const points: ForecastPoint[] = []
  const growthPerDay = item.growth_rate_per_day ?? 0.1

  for (let d = -30; d <= 90; d += 5) {
    const date = new Date(today)
    date.setDate(today.getDate() + d)
    const label = `${date.getMonth() + 1}/${date.getDate()}`
    const usage = Math.min(100, item.usage_pct + growthPerDay * d)
    points.push({ day: label, usage_pct: Math.max(0, usage), projected: d > 0 })
  }
  return points
}

interface ForecastChartProps {
  item: CapacityQuotaItem
}

function ForecastChart({ item }: ForecastChartProps) {
  const data = buildForecastData(item)

  return (
    <div className="mt-4">
      <p className="text-xs font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>
        90-day forecast: {item.name} ({item.quota_name})
      </p>
      <ResponsiveContainer width="100%" height={180}>
        <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <XAxis
            dataKey="day"
            tick={{ fontSize: 9, fill: 'var(--text-muted)' }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            domain={[0, 100]}
            tickFormatter={(v: number) => `${v}%`}
            tick={{ fontSize: 9, fill: 'var(--text-muted)' }}
            axisLine={false}
            tickLine={false}
            width={36}
          />
          <Tooltip
            contentStyle={{
              background: 'var(--bg-surface)',
              border: '1px solid var(--border)',
              fontSize: 11,
            }}
            labelStyle={{ color: 'var(--text-primary)' }}
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            formatter={(value: any) => [value != null ? `${Number(value).toFixed(1)}%` : '—', 'Usage']}
          />
          <ReferenceLine y={80} stroke="var(--accent-yellow)" strokeDasharray="4 2" />
          <ReferenceLine y={90} stroke="var(--accent-red)" strokeDasharray="4 2" />
          <Legend
            wrapperStyle={{ fontSize: 10, color: 'var(--text-muted)' }}
          />
          <Line
            dataKey="usage_pct"
            name="Usage %"
            dot={false}
            strokeWidth={2}
            stroke="var(--accent-blue)"
          />
        </LineChart>
      </ResponsiveContainer>
      <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
        Dashed lines: 80% warning / 90% critical thresholds
        {item.projected_exhaustion_date && (
          <> &nbsp;·&nbsp; Projected exhaustion: <strong style={{ color: 'var(--accent-red)' }}>{item.projected_exhaustion_date.slice(0, 10)}</strong></>
        )}
      </p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Quota headroom table
// ---------------------------------------------------------------------------

interface QuotaTableProps {
  items: CapacityQuotaItem[]
  snapshotCount: number
}

function QuotaTable({ items, snapshotCount }: QuotaTableProps) {
  const [expandedRow, setExpandedRow] = useState<string | null>(null)

  if (items.length === 0) {
    return (
      <p className="text-sm py-6 text-center" style={{ color: 'var(--text-muted)' }}>
        No quota data available.
      </p>
    )
  }

  return (
    <div className="space-y-4">
      <div className="rounded overflow-hidden" style={{ border: '1px solid var(--border)' }}>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead style={{ color: 'var(--text-secondary)', fontSize: '11px' }}>Resource</TableHead>
              <TableHead style={{ color: 'var(--text-secondary)', fontSize: '11px' }}>Quota</TableHead>
              <TableHead style={{ color: 'var(--text-secondary)', fontSize: '11px' }}>Used / Limit</TableHead>
              <TableHead style={{ color: 'var(--text-secondary)', fontSize: '11px' }}>Usage %</TableHead>
              <TableHead style={{ color: 'var(--text-secondary)', fontSize: '11px' }}>Available</TableHead>
              <TableHead style={{ color: 'var(--text-secondary)', fontSize: '11px' }}>Days to Exhaust</TableHead>
              <TableHead style={{ color: 'var(--text-secondary)', fontSize: '11px' }}>Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((item) => {
              const key = `${item.resource_category}/${item.quota_name}`
              const isExpanded = expandedRow === key
              return (
                <React.Fragment key={key}>
                  <TableRow
                    onClick={() => setExpandedRow(isExpanded ? null : key)}
                    style={{ cursor: 'pointer' }}
                  >
                    <TableCell className="text-xs font-medium" style={{ color: 'var(--text-primary)' }}>
                      {item.name}
                    </TableCell>
                    <TableCell className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                      {item.quota_name}
                    </TableCell>
                    <TableCell className="text-xs font-mono" style={{ color: 'var(--text-primary)' }}>
                      {item.current_value} / {item.limit}
                    </TableCell>
                    <TableCell className="text-xs" style={{ color: 'var(--text-primary)' }}>
                      <div className="flex items-center gap-2">
                        <div
                          className="h-1.5 rounded-full overflow-hidden"
                          style={{ width: 60, background: 'var(--border)' }}
                        >
                          <div
                            className="h-full rounded-full"
                            style={{
                              width: `${Math.min(100, item.usage_pct)}%`,
                              background: item.traffic_light === 'red'
                                ? 'var(--accent-red)'
                                : item.traffic_light === 'yellow'
                                  ? 'var(--accent-yellow)'
                                  : 'var(--accent-green)',
                            }}
                          />
                        </div>
                        {item.usage_pct.toFixed(1)}%
                      </div>
                    </TableCell>
                    <TableCell className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                      {item.available.toLocaleString()}
                    </TableCell>
                    <TableCell className="text-xs" style={{ color: 'var(--text-primary)' }}>
                      {item.days_to_exhaustion != null
                        ? `${item.days_to_exhaustion}d`
                        : '—'}
                    </TableCell>
                    <TableCell>
                      <TrafficBadge light={item.traffic_light} />
                    </TableCell>
                  </TableRow>
                  {isExpanded && snapshotCount >= 3 && (
                    <TableRow>
                      <TableCell colSpan={7} style={{ background: 'var(--bg-subtle)' }}>
                        <ForecastChart item={item} />
                      </TableCell>
                    </TableRow>
                  )}
                  {isExpanded && snapshotCount < 3 && (
                    <TableRow>
                      <TableCell colSpan={7} style={{ background: 'var(--bg-subtle)' }}>
                        <p className="text-xs py-2 text-center" style={{ color: 'var(--text-muted)' }}>
                          Forecast requires at least 3 snapshots ({snapshotCount} collected so far).
                        </p>
                      </TableCell>
                    </TableRow>
                  )}
                </React.Fragment>
              )
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// IP address space table
// ---------------------------------------------------------------------------

interface IPTableProps {
  items: SubnetHeadroomItem[]
}

function IPTable({ items }: IPTableProps) {
  if (items.length === 0) {
    return (
      <p className="text-sm py-6 text-center" style={{ color: 'var(--text-muted)' }}>
        No subnet data available.
      </p>
    )
  }

  return (
    <div className="rounded overflow-hidden" style={{ border: '1px solid var(--border)' }}>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead style={{ color: 'var(--text-secondary)', fontSize: '11px' }}>VNet</TableHead>
            <TableHead style={{ color: 'var(--text-secondary)', fontSize: '11px' }}>Subnet</TableHead>
            <TableHead style={{ color: 'var(--text-secondary)', fontSize: '11px' }}>CIDR</TableHead>
            <TableHead style={{ color: 'var(--text-secondary)', fontSize: '11px' }}>Total IPs</TableHead>
            <TableHead style={{ color: 'var(--text-secondary)', fontSize: '11px' }}>Available</TableHead>
            <TableHead style={{ color: 'var(--text-secondary)', fontSize: '11px' }}>Usage %</TableHead>
            <TableHead style={{ color: 'var(--text-secondary)', fontSize: '11px' }}>Status</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((item) => (
            <TableRow key={`${item.vnet_name}/${item.subnet_name}`}>
              <TableCell className="text-xs font-medium" style={{ color: 'var(--text-primary)' }}>
                {item.vnet_name}
              </TableCell>
              <TableCell className="text-xs" style={{ color: 'var(--text-primary)' }}>
                {item.subnet_name}
              </TableCell>
              <TableCell className="text-xs font-mono" style={{ color: 'var(--text-secondary)' }}>
                {item.address_prefix}
              </TableCell>
              <TableCell className="text-xs" style={{ color: 'var(--text-primary)' }}>
                {item.total_ips.toLocaleString()}
              </TableCell>
              <TableCell className="text-xs" style={{ color: 'var(--text-primary)' }}>
                {item.available_ips.toLocaleString()}
              </TableCell>
              <TableCell className="text-xs" style={{ color: 'var(--text-primary)' }}>
                <div className="flex items-center gap-2">
                  <div
                    className="h-1.5 rounded-full overflow-hidden"
                    style={{ width: 60, background: 'var(--border)' }}
                  >
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${Math.min(100, item.usage_pct)}%`,
                        background: item.traffic_light === 'red'
                          ? 'var(--accent-red)'
                          : item.traffic_light === 'yellow'
                            ? 'var(--accent-yellow)'
                            : 'var(--accent-green)',
                      }}
                    />
                  </div>
                  {item.usage_pct.toFixed(1)}%
                </div>
              </TableCell>
              <TableCell>
                <TrafficBadge light={item.traffic_light} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// AKS node pool table
// ---------------------------------------------------------------------------

interface AKSTableProps {
  items: AKSNodePoolHeadroomItem[]
}

function AKSTable({ items }: AKSTableProps) {
  if (items.length === 0) {
    return (
      <p className="text-sm py-6 text-center" style={{ color: 'var(--text-muted)' }}>
        No AKS node pool data available.
      </p>
    )
  }

  return (
    <div className="rounded overflow-hidden" style={{ border: '1px solid var(--border)' }}>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead style={{ color: 'var(--text-secondary)', fontSize: '11px' }}>Cluster</TableHead>
            <TableHead style={{ color: 'var(--text-secondary)', fontSize: '11px' }}>Pool</TableHead>
            <TableHead style={{ color: 'var(--text-secondary)', fontSize: '11px' }}>VM Size</TableHead>
            <TableHead style={{ color: 'var(--text-secondary)', fontSize: '11px' }}>Nodes (cur/max)</TableHead>
            <TableHead style={{ color: 'var(--text-secondary)', fontSize: '11px' }}>Available</TableHead>
            <TableHead style={{ color: 'var(--text-secondary)', fontSize: '11px' }}>Usage %</TableHead>
            <TableHead style={{ color: 'var(--text-secondary)', fontSize: '11px' }}>Status</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((item) => (
            <TableRow key={`${item.cluster_name}/${item.pool_name}`}>
              <TableCell className="text-xs font-medium" style={{ color: 'var(--text-primary)' }}>
                {item.cluster_name}
              </TableCell>
              <TableCell className="text-xs" style={{ color: 'var(--text-primary)' }}>
                {item.pool_name}
              </TableCell>
              <TableCell className="text-xs font-mono" style={{ color: 'var(--text-secondary)' }}>
                {item.vm_size}
              </TableCell>
              <TableCell className="text-xs font-mono" style={{ color: 'var(--text-primary)' }}>
                {item.current_nodes} / {item.max_nodes}
              </TableCell>
              <TableCell className="text-xs" style={{ color: 'var(--text-primary)' }}>
                {item.available_nodes}
              </TableCell>
              <TableCell className="text-xs" style={{ color: 'var(--text-primary)' }}>
                <div className="flex items-center gap-2">
                  <div
                    className="h-1.5 rounded-full overflow-hidden"
                    style={{ width: 60, background: 'var(--border)' }}
                  >
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${Math.min(100, item.usage_pct)}%`,
                        background: item.traffic_light === 'red'
                          ? 'var(--accent-red)'
                          : item.traffic_light === 'yellow'
                            ? 'var(--accent-yellow)'
                            : 'var(--accent-green)',
                      }}
                    />
                  </div>
                  {item.usage_pct.toFixed(1)}%
                </div>
              </TableCell>
              <TableCell>
                <TrafficBadge light={item.traffic_light} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Section heading
// ---------------------------------------------------------------------------

function SectionHeading({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="mb-3">
      <h3 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>{title}</h3>
      {subtitle && <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>{subtitle}</p>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// CapacityTab
// ---------------------------------------------------------------------------

const LOCATIONS = ['eastus', 'eastus2', 'westus', 'westus2', 'westeurope', 'northeurope', 'southeastasia']

interface CapacityTabProps {
  subscriptionId: string | undefined
}

export function CapacityTab({ subscriptionId }: CapacityTabProps) {
  const [location, setLocation] = useState('eastus')
  const [headroom, setHeadroom] = useState<CapacityHeadroomResponse | null>(null)
  const [ipSpace, setIPSpace] = useState<IPSpaceHeadroomResponse | null>(null)
  const [aks, setAKS] = useState<AKSHeadroomResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchAll = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const sub = subscriptionId ?? ''
      const qsBase = sub ? `subscription_id=${encodeURIComponent(sub)}` : ''
      const qsLoc = qsBase ? `${qsBase}&location=${encodeURIComponent(location)}` : `location=${encodeURIComponent(location)}`

      const [hRes, ipRes, aksRes] = await Promise.all([
        fetch(`/api/proxy/capacity/headroom${qsLoc ? `?${qsLoc}` : ''}`),
        fetch(`/api/proxy/capacity/ip-space${qsBase ? `?${qsBase}` : ''}`),
        fetch(`/api/proxy/capacity/aks${qsBase ? `?${qsBase}` : ''}`),
      ])

      const [hData, ipData, aksData] = await Promise.all([
        hRes.json() as Promise<CapacityHeadroomResponse & { error?: string }>,
        ipRes.json() as Promise<IPSpaceHeadroomResponse & { error?: string }>,
        aksRes.json() as Promise<AKSHeadroomResponse & { error?: string }>,
      ])

      if (hData.error && !hData.top_constrained?.length) {
        setError(hData.error)
      }

      setHeadroom(hData)
      setIPSpace(ipData)
      setAKS(aksData)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load capacity data')
    } finally {
      setLoading(false)
    }
  }, [subscriptionId, location])

  useEffect(() => {
    fetchAll()
  }, [fetchAll])

  const allQuotaItems = headroom?.top_constrained ?? []
  const allSubnetItems = ipSpace?.subnets ?? []
  const allAKSItems = aks?.clusters ?? []
  const allItems: Array<{ traffic_light: TrafficLight }> = [
    ...allQuotaItems,
    ...allSubnetItems,
    ...allAKSItems,
  ]

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h2 className="text-lg font-semibold" style={{ color: 'var(--text-primary)' }}>
            Capacity &amp; Headroom
          </h2>
          <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
            Quota usage, IP address space, and AKS node pool headroom
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            className="text-sm rounded px-2 py-1.5"
            style={{
              background: 'var(--bg-surface)',
              border: '1px solid var(--border)',
              color: 'var(--text-primary)',
            }}
          >
            {LOCATIONS.map((loc) => (
              <option key={loc} value={loc}>{loc}</option>
            ))}
          </select>
          <Button
            size="sm"
            variant="outline"
            onClick={fetchAll}
            disabled={loading}
            style={{ borderColor: 'var(--border)', color: 'var(--text-primary)' }}
          >
            <RefreshCw className={`h-4 w-4 mr-1 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        </div>
      </div>

      {error && (
        <Alert
          style={{
            borderColor: 'var(--accent-red)',
            background: 'color-mix(in srgb, var(--accent-red) 10%, transparent)',
          }}
        >
          <AlertDescription style={{ color: 'var(--accent-red)' }}>{error}</AlertDescription>
        </Alert>
      )}

      {loading ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-20 rounded-lg" />)}
          </div>
          <Skeleton className="h-64 rounded-lg" />
          <Skeleton className="h-48 rounded-lg" />
        </div>
      ) : (
        <>
          {/* Summary cards — aggregate across all sections */}
          {allItems.length > 0 && <SummaryCards items={allItems} />}

          {/* Quota headroom */}
          <div
            className="rounded-lg p-4"
            style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
          >
            <SectionHeading
              title="Quota Headroom"
              subtitle={
                headroom?.snapshot_count != null
                  ? `${headroom.snapshot_count} snapshot${headroom.snapshot_count !== 1 ? 's' : ''} collected · ${location} · click a row to ${headroom.snapshot_count >= 3 ? 'view 90-day forecast' : 'see forecast status'}`
                  : `${location}`
              }
            />
            {headroom?.data_note && (
              <p className="text-xs mb-3" style={{ color: 'var(--text-muted)' }}>
                <Gauge className="inline h-3 w-3 mr-1" />{headroom.data_note}
              </p>
            )}
            <QuotaTable
              items={allQuotaItems}
              snapshotCount={headroom?.snapshot_count ?? 0}
            />
          </div>

          {/* IP address space */}
          <div
            className="rounded-lg p-4"
            style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
          >
            <SectionHeading
              title="IP Address Space"
              subtitle="Subnet-level available IP addresses"
            />
            {ipSpace?.note && (
              <p className="text-xs mb-3" style={{ color: 'var(--text-muted)' }}>{ipSpace.note}</p>
            )}
            <IPTable items={allSubnetItems} />
          </div>

          {/* AKS node pool headroom */}
          <div
            className="rounded-lg p-4"
            style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
          >
            <SectionHeading
              title="AKS Node Pool Headroom"
              subtitle="Available scale capacity per node pool"
            />
            <AKSTable items={allAKSItems} />
          </div>
        </>
      )}
    </div>
  )
}
