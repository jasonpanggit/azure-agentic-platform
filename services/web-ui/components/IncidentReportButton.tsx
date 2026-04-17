'use client'

import React, { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Download, Loader2 } from 'lucide-react'

interface Props {
  incidentId: string
  incidentTitle?: string
}

/**
 * IncidentReportButton — fetches and triggers a browser download of the
 * Markdown incident report for the given incidentId.
 */
export function IncidentReportButton({ incidentId, incidentTitle }: Props) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleDownload() {
    setLoading(true)
    setError(null)

    try {
      const res = await fetch(
        `/api/proxy/incidents/${encodeURIComponent(incidentId)}/report/markdown`,
        { cache: 'no-store' }
      )

      if (!res.ok) {
        const text = await res.text()
        setError(`Failed to generate report (${res.status}): ${text.slice(0, 120)}`)
        return
      }

      const markdown = await res.text()

      // Trigger browser download
      const blob = new Blob([markdown], { type: 'text/markdown' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `incident-${incidentId}.md`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col gap-1">
      <Button
        variant="outline"
        size="sm"
        onClick={handleDownload}
        disabled={loading}
        className="gap-1.5"
        title={incidentTitle ? `Export report for: ${incidentTitle}` : 'Export incident report'}
      >
        {loading ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <Download className="h-3.5 w-3.5" />
        )}
        {loading ? 'Generating…' : 'Export Report'}
      </Button>

      {error && (
        <p className="text-xs" style={{ color: 'var(--accent-red)' }}>
          {error}
        </p>
      )}
    </div>
  )
}
