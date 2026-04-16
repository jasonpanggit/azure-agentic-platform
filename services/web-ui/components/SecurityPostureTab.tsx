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
  CartesianGrid,
} from 'recharts'
import { RefreshCw, MessageSquare } from 'lucide-react'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ScoreColor = 'green' | 'yellow' | 'red'
type Severity = 'Critical' | 'High' | 'Medium' | 'Low' | 'Unknown'

interface SubScores {
  defender_secure_score: number
  policy_compliance: number
  custom_controls: number
}

interface TrendPoint {
  date: string
  score: number
}

interface PostureResponse {
  composite_score: number
  color: ScoreColor
  sub_scores: SubScores
  trend: TrendPoint[]
  warnings?: string[]
  error?: string
}

interface Finding {
  finding: string
  severity: Severity
  resource_id: string
  resource_name: string
  recommendation: string
  control: string
}

interface FindingsResponse {
  findings: Finding[]
  total: number
  error?: string
}

interface SecurityPostureTabProps {
  subscriptionId?: string
  /** Called when user clicks "Remediate via agent" — opens chat with context */
  onOpenChat?: (context: string) => void
}

// ---------------------------------------------------------------------------
// Color helpers — CSS semantic tokens only, NO hardcoded Tailwind colors
// ---------------------------------------------------------------------------

function scoreColorStyle(color: ScoreColor): React.CSSProperties {
  const map: Record<ScoreColor, string> = {
    green: 'var(--accent-green)',
    yellow: 'var(--accent-yellow)',
    red: 'var(--accent-red)',
  }
  return { color: map[color] }
}

function scoreBgStyle(color: ScoreColor): React.CSSProperties {
  const map: Record<ScoreColor, string> = {
    green: 'color-mix(in srgb, var(--accent-green) 12%, transparent)',
    yellow: 'color-mix(in srgb, var(--accent-yellow) 12%, transparent)',
    red: 'color-mix(in srgb, var(--accent-red) 12%, transparent)',
  }
  return {
    background: map[color],
    border: `1px solid color-mix(in srgb, ${scoreColorStyle(color).color} 30%, transparent)`,
  }
}

function severityStyle(severity: Severity): React.CSSProperties {
  const map: Record<Severity, string> = {
    Critical: 'var(--accent-red)',
    High: 'color-mix(in srgb, var(--accent-red) 70%, var(--accent-yellow))',
    Medium: 'var(--accent-yellow)',
    Low: 'var(--accent-blue)',
    Unknown: 'var(--text-secondary)',
  }
  const c = map[severity]
  return {
    background: `color-mix(in srgb, ${c} 15%, transparent)`,
    color: c,
    border: `1px solid color-mix(in srgb, ${c} 30%, transparent)`,
  }
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ScoreGauge({ score, color }: { score: number; color: ScoreColor }) {
  return (
    <div
      className="flex flex-col items-center justify-center rounded-2xl p-8"
      style={scoreBgStyle(color)}
    >
      <span
        className="text-7xl font-bold tabular-nums"
        style={scoreColorStyle(color)}
      >
        {score.toFixed(0)}
      </span>
      <span className="mt-2 text-sm font-medium uppercase tracking-widest" style={{ color: 'var(--text-secondary)' }}>
        Security Score
      </span>
      <span className="mt-1 text-xs" style={{ color: 'var(--text-secondary)' }}>
        out of 100
      </span>
    </div>
  )
}

interface SubScoreCardProps {
  label: string
  score: number
  weight: string
  description: string
}

function SubScoreCard({ label, score, weight, description }: SubScoreCardProps) {
  const color: ScoreColor = score >= 75 ? 'green' : score >= 50 ? 'yellow' : 'red'
  return (
    <Card style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
      <CardContent className="p-5">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>{label}</p>
            <p className="text-xs mt-0.5" style={{ color: 'var(--text-secondary)' }}>{description}</p>
          </div>
          <Badge style={severityStyle(score >= 75 ? 'Low' : score >= 50 ? 'Medium' : 'High')}>
            {weight}
          </Badge>
        </div>
        <div className="mt-4 flex items-end gap-2">
          <span className="text-4xl font-bold tabular-nums" style={scoreColorStyle(color)}>
            {score.toFixed(0)}
          </span>
          <span className="mb-1 text-sm" style={{ color: 'var(--text-secondary)' }}>/100</span>
        </div>
        {/* Progress bar */}
        <div
          className="mt-3 h-1.5 rounded-full overflow-hidden"
          style={{ background: 'var(--border)' }}
        >
          <div
            className="h-full rounded-full transition-all duration-500"
            style={{ width: `${Math.min(100, score)}%`, background: scoreColorStyle(color).color }}
          />
        </div>
      </CardContent>
    </Card>
  )
}

function TrendChart({ data }: { data: TrendPoint[] }) {
  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-40" style={{ color: 'var(--text-secondary)' }}>
        No trend data available yet
      </div>
    )
  }
  return (
    <ResponsiveContainer width="100%" height={200}>
      <LineChart data={data} margin={{ top: 4, right: 16, left: -16, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis
          dataKey="date"
          tick={{ fontSize: 11, fill: 'var(--text-secondary)' }}
          tickLine={false}
          axisLine={false}
        />
        <YAxis
          domain={[0, 100]}
          tick={{ fontSize: 11, fill: 'var(--text-secondary)' }}
          tickLine={false}
          axisLine={false}
        />
        <Tooltip
          contentStyle={{
            background: 'var(--bg-surface)',
            border: '1px solid var(--border)',
            borderRadius: 8,
            color: 'var(--text-primary)',
          }}
          formatter={(value: any) => [value != null ? Number(value).toFixed(1) : '—', 'Score']}
        />
        <Line
          type="monotone"
          dataKey="score"
          stroke="var(--accent-blue)"
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 4, fill: 'var(--accent-blue)' }}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}

function FindingsTable({ findings, onRemediate }: { findings: Finding[]; onRemediate: (f: Finding) => void }) {
  if (findings.length === 0) {
    return (
      <div className="flex items-center justify-center py-12" style={{ color: 'var(--text-secondary)' }}>
        No findings — security posture looks clean.
      </div>
    )
  }
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow style={{ borderBottom: '1px solid var(--border)' }}>
            <TableHead style={{ color: 'var(--text-secondary)' }}>Finding</TableHead>
            <TableHead style={{ color: 'var(--text-secondary)' }}>Severity</TableHead>
            <TableHead style={{ color: 'var(--text-secondary)' }}>Resource</TableHead>
            <TableHead style={{ color: 'var(--text-secondary)' }}>Control</TableHead>
            <TableHead style={{ color: 'var(--text-secondary)' }}>Recommendation</TableHead>
            <TableHead style={{ color: 'var(--text-secondary)' }}></TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {findings.map((f, idx) => (
            <TableRow
              key={idx}
              style={{ borderBottom: '1px solid var(--border)' }}
            >
              <TableCell className="font-medium max-w-xs" style={{ color: 'var(--text-primary)' }}>
                <span className="line-clamp-2">{f.finding}</span>
              </TableCell>
              <TableCell>
                <Badge style={severityStyle(f.severity as Severity)}>{f.severity}</Badge>
              </TableCell>
              <TableCell style={{ color: 'var(--text-secondary)' }}>
                <span className="font-mono text-xs">{f.resource_name || '—'}</span>
              </TableCell>
              <TableCell style={{ color: 'var(--text-secondary)' }}>
                <span className="text-xs">{f.control || '—'}</span>
              </TableCell>
              <TableCell className="max-w-xs" style={{ color: 'var(--text-secondary)' }}>
                <span className="text-xs line-clamp-2">{f.recommendation || '—'}</span>
              </TableCell>
              <TableCell>
                <Button
                  size="sm"
                  variant="outline"
                  className="whitespace-nowrap text-xs gap-1"
                  style={{
                    borderColor: 'var(--border)',
                    color: 'var(--accent-blue)',
                  }}
                  onClick={() => onRemediate(f)}
                >
                  <MessageSquare className="h-3 w-3" />
                  Remediate
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Loading skeleton
// ---------------------------------------------------------------------------

function PostureSkeleton() {
  return (
    <div className="space-y-6">
      <div className="flex gap-6">
        <Skeleton className="h-52 w-52 rounded-2xl" />
        <div className="flex-1 grid grid-cols-3 gap-4">
          {[0, 1, 2].map((i) => <Skeleton key={i} className="h-full rounded-xl" />)}
        </div>
      </div>
      <Skeleton className="h-52 w-full rounded-xl" />
      <Skeleton className="h-64 w-full rounded-xl" />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function SecurityPostureTab({ subscriptionId, onOpenChat }: SecurityPostureTabProps) {
  const [posture, setPosture] = useState<PostureResponse | null>(null)
  const [findings, setFindings] = useState<Finding[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    if (!subscriptionId) {
      setLoading(false)
      return
    }
    setLoading(true)
    setError(null)
    try {
      const [postureRes, findingsRes] = await Promise.all([
        fetch(`/api/proxy/security/posture?subscription_id=${encodeURIComponent(subscriptionId)}`),
        fetch(`/api/proxy/security/findings?subscription_id=${encodeURIComponent(subscriptionId)}&limit=25`),
      ])
      const postureData: PostureResponse = await postureRes.json()
      const findingsData: FindingsResponse = await findingsRes.json()

      if (postureData.error && !postureData.composite_score) {
        setError(postureData.error)
      } else {
        setPosture(postureData)
      }
      setFindings(findingsData.findings ?? [])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load security posture')
    } finally {
      setLoading(false)
    }
  }, [subscriptionId])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  function handleRemediate(finding: Finding) {
    if (onOpenChat) {
      const context = [
        `Please help me remediate the following security finding:`,
        `Finding: ${finding.finding}`,
        `Severity: ${finding.severity}`,
        `Resource: ${finding.resource_name || finding.resource_id || 'Unknown'}`,
        finding.control ? `Control: ${finding.control}` : '',
        finding.recommendation ? `Recommendation: ${finding.recommendation}` : '',
      ].filter(Boolean).join('\n')
      onOpenChat(context)
    }
  }

  if (!subscriptionId) {
    return (
      <div className="p-6 flex items-center justify-center" style={{ color: 'var(--text-secondary)' }}>
        Select a subscription to view security posture.
      </div>
    )
  }

  if (loading) {
    return (
      <div className="p-6">
        <PostureSkeleton />
      </div>
    )
  }

  if (error && !posture) {
    return (
      <div className="p-6">
        <Alert style={{ borderColor: 'var(--accent-red)', background: 'color-mix(in srgb, var(--accent-red) 8%, transparent)' }}>
          <AlertDescription style={{ color: 'var(--text-primary)' }}>
            {error}
          </AlertDescription>
        </Alert>
      </div>
    )
  }

  const score = posture?.composite_score ?? 0
  const color = posture?.color ?? 'red'
  const sub = posture?.sub_scores ?? { defender_secure_score: 0, policy_compliance: 0, custom_controls: 0 }
  const trend = posture?.trend ?? []
  const warnings = posture?.warnings ?? []

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold" style={{ color: 'var(--text-primary)' }}>
            Security Posture
          </h2>
          <p className="text-sm mt-0.5" style={{ color: 'var(--text-secondary)' }}>
            Composite score across Defender, Policy Compliance, and Controls
          </p>
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={fetchData}
          className="gap-1.5"
          style={{ borderColor: 'var(--border)', color: 'var(--text-secondary)' }}
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Refresh
        </Button>
      </div>

      {/* Warnings */}
      {warnings.length > 0 && (
        <Alert style={{ borderColor: 'var(--accent-yellow)', background: 'color-mix(in srgb, var(--accent-yellow) 8%, transparent)' }}>
          <AlertDescription style={{ color: 'var(--text-primary)' }}>
            {warnings.join(' · ')}
          </AlertDescription>
        </Alert>
      )}

      {/* Score gauge + sub-score cards */}
      <div className="flex flex-col lg:flex-row gap-6">
        <div className="flex-shrink-0">
          <ScoreGauge score={score} color={color} />
        </div>
        <div className="flex-1 grid grid-cols-1 sm:grid-cols-3 gap-4">
          <SubScoreCard
            label="Defender Secure Score"
            score={sub.defender_secure_score}
            weight="50%"
            description="Microsoft Defender for Cloud"
          />
          <SubScoreCard
            label="Policy Compliance"
            score={sub.policy_compliance}
            weight="30%"
            description="Azure Policy compliance state"
          />
          <SubScoreCard
            label="Custom Controls"
            score={sub.custom_controls}
            weight="20%"
            description="Exposure management & custom"
          />
        </div>
      </div>

      {/* 30-day trend */}
      <Card style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
        <CardContent className="p-5">
          <p className="text-sm font-medium mb-4" style={{ color: 'var(--text-primary)' }}>
            30-Day Score Trend
          </p>
          <TrendChart data={trend} />
        </CardContent>
      </Card>

      {/* Findings table */}
      <Card style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
        <CardContent className="p-5">
          <div className="flex items-center justify-between mb-4">
            <p className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>
              Top Findings
              {findings.length > 0 && (
                <Badge
                  className="ml-2 text-xs"
                  style={{
                    background: 'color-mix(in srgb, var(--accent-red) 12%, transparent)',
                    color: 'var(--accent-red)',
                    border: '1px solid color-mix(in srgb, var(--accent-red) 25%, transparent)',
                  }}
                >
                  {findings.length}
                </Badge>
              )}
            </p>
          </div>
          <FindingsTable findings={findings} onRemediate={handleRemediate} />
        </CardContent>
      </Card>
    </div>
  )
}
