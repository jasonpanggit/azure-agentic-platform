'use client'

import { GitCommit, ExternalLink } from 'lucide-react'

interface DeploymentBadgeProps {
  deployment: {
    author: string
    commit_sha: string
    pipeline_url?: string
    time_before_incident_min: number | null
  }
}

/**
 * DeploymentBadge — compact inline badge surfacing deployment-to-incident causation.
 *
 * Shows: "Deployed Xmin before incident by @author — commit abc123"
 * Used in incident detail panels to highlight correlated deployments.
 */
export function DeploymentBadge({ deployment }: DeploymentBadgeProps) {
  const { author, commit_sha, pipeline_url, time_before_incident_min } = deployment
  const shortSha = commit_sha ? commit_sha.slice(0, 7) : '???????'

  const timeLabel =
    time_before_incident_min !== null && time_before_incident_min !== undefined
      ? time_before_incident_min > 0
        ? `${Math.round(time_before_incident_min)}min before incident`
        : `${Math.abs(Math.round(time_before_incident_min))}min after incident`
      : 'unknown timing'

  return (
    <span
      className="inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs font-medium"
      style={{
        background: 'color-mix(in srgb, var(--accent-yellow) 12%, transparent)',
        color: 'var(--accent-yellow)',
        border: '1px solid color-mix(in srgb, var(--accent-yellow) 30%, transparent)',
      }}
      title={`Pipeline: ${pipeline_url || 'N/A'}`}
    >
      <GitCommit className="h-3 w-3 shrink-0" aria-hidden="true" />
      <span>
        Deployed {timeLabel} by{' '}
        <strong>@{author}</strong>
        {' — '}
        {pipeline_url ? (
          <a
            href={pipeline_url}
            target="_blank"
            rel="noopener noreferrer"
            className="underline underline-offset-2 hover:opacity-80 inline-flex items-center gap-0.5"
            onClick={(e) => e.stopPropagation()}
          >
            {shortSha}
            <ExternalLink className="h-2.5 w-2.5" aria-hidden="true" />
          </a>
        ) : (
          <code className="font-mono">{shortSha}</code>
        )}
      </span>
    </span>
  )
}
