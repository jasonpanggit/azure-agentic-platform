'use client'

import React, { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  ChevronDown,
  ChevronRight,
  Plus,
  RefreshCw,
  MoreHorizontal,
} from 'lucide-react'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

// ─── Types ────────────────────────────────────────────────────────────────────

interface ManagedSubscription {
  subscription_id: string
  display_name: string
  credential_type: 'spn' | 'mi'
  client_id: string | null
  permission_status: Record<string, string>
  secret_expires_at: string | null
  days_until_expiry: number | null
  last_validated_at: string | null
  monitoring_enabled: boolean
  environment: string
}

// ─── Permission icons ─────────────────────────────────────────────────────────

function PermIcon({ status }: { status: string }) {
  if (status === 'granted') return <span title="Granted">✅</span>
  if (status === 'missing') return <span title="Missing">⚠️</span>
  return <span title="Unknown">❓</span>
}

// ─── Expiry badge ─────────────────────────────────────────────────────────────

function ExpiryBadge({ daysUntilExpiry, secretExpiresAt }: {
  daysUntilExpiry: number | null
  secretExpiresAt: string | null
}) {
  if (!secretExpiresAt) {
    return (
      <Badge
        style={{ background: 'color-mix(in srgb, var(--accent-yellow) 15%, transparent)' }}
        className="text-xs"
        title="No expiry date tracked"
      >
        ⚠️ No expiry
      </Badge>
    )
  }
  if (daysUntilExpiry !== null && daysUntilExpiry <= 0) {
    return (
      <Badge
        style={{ background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)' }}
        className="text-xs text-[var(--accent-red)]"
      >
        🔴 Expired
      </Badge>
    )
  }
  if (daysUntilExpiry !== null && daysUntilExpiry <= 30) {
    return (
      <Badge
        style={{ background: 'color-mix(in srgb, var(--accent-yellow) 15%, transparent)' }}
        className="text-xs"
      >
        🟡 {daysUntilExpiry}d
      </Badge>
    )
  }
  return (
    <Badge
      style={{ background: 'color-mix(in srgb, var(--accent-green) 15%, transparent)' }}
      className="text-xs text-[var(--accent-green)]"
    >
      🟢 {daysUntilExpiry}d
    </Badge>
  )
}

// ─── Info Banner ─────────────────────────────────────────────────────────────

function InfoBanner() {
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    if (typeof window !== 'undefined') {
      setExpanded(localStorage.getItem('aap.spnBannerExpanded') === 'true')
    }
  }, [])

  const toggle = () => {
    const next = !expanded
    setExpanded(next)
    if (typeof window !== 'undefined') {
      localStorage.setItem('aap.spnBannerExpanded', String(next))
    }
  }

  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-canvas)] p-4 mb-4">
      <button
        onClick={toggle}
        className="flex w-full items-center justify-between text-sm font-medium text-[var(--text-primary)]"
      >
        <span>ℹ️ How to onboard a subscription</span>
        {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
      </button>

      {expanded && (
        <div className="mt-4 space-y-4 text-sm text-[var(--text-secondary)]">
          <div>
            <p className="font-semibold text-[var(--text-primary)] mb-1">
              Step 1: Create an App Registration (requires Entra ID access)
            </p>
            <ul className="ml-4 space-y-1 list-disc">
              <li>Azure Portal → Entra ID → App Registrations → New Registration</li>
              <li>Name: e.g. <code>aap-monitor-&lt;subscription-name&gt;</code></li>
              <li>Note the <strong>Application (client) ID</strong> and <strong>Directory (tenant) ID</strong></li>
              <li>Go to Certificates &amp; Secrets → New client secret</li>
              <li>⚠️ Copy the secret value immediately — it is shown once only</li>
            </ul>
          </div>

          <div>
            <p className="font-semibold text-[var(--text-primary)] mb-1">
              Step 2: Grant required roles on the target subscription
            </p>
            <p className="mb-2">
              Prerequisite: Owner or User Access Administrator on the target subscription.
            </p>
            <div className="bg-[var(--bg-surface)] rounded p-3 font-mono text-xs mb-2">
              {`./setup_spn.sh \\
  --subscription-id <id> \\
  --client-id <client-id> \\
  --tenant-id <tenant-id> \\
  --onboard \\
  --api-url https://your-api-gateway-url`}
            </div>
            <p className="text-xs">
              Required roles: Reader · Monitoring Reader · Security Reader ·
              Cost Management Reader · Virtual Machine Contributor ·
              Azure Kubernetes Service Contributor · Container Apps Contributor
            </p>
            <a
              href="/scripts/setup_spn.sh"
              download
              className="inline-flex items-center gap-1 text-[var(--accent-blue)] text-xs mt-1 hover:underline"
            >
              ⬇ Download setup_spn.sh
            </a>
          </div>

          <div>
            <p className="font-semibold text-[var(--text-primary)] mb-1">
              Step 3: Click &quot;+ Add&quot; above and enter your credentials
            </p>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

export function MonitoredSubscriptionsTab() {
  const [subscriptions, setSubscriptions] = useState<ManagedSubscription[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showAddDrawer, setShowAddDrawer] = useState(false)
  const [updateTarget, setUpdateTarget] = useState<string | null>(null)

  const fetchSubscriptions = async () => {
    setLoading(true)
    setError(null)
    try {
      const resp = await fetch('/api/proxy/subscriptions/managed')
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json()
      // Normalise API field names: managed endpoint returns `id`/`name`, component expects `subscription_id`/`display_name`
      const normalised = (data.subscriptions ?? []).map((s: Record<string, unknown>) => ({
        subscription_id: s.subscription_id ?? s.id,
        display_name: s.display_name ?? s.name ?? s.id,
        credential_type: s.credential_type ?? 'mi',
        client_id: s.client_id ?? null,
        permission_status: (s.permission_status as Record<string, string>) ?? {},
        secret_expires_at: s.secret_expires_at ?? null,
        days_until_expiry: s.days_until_expiry ?? null,
        last_validated_at: s.last_validated_at ?? null,
        monitoring_enabled: s.monitoring_enabled ?? true,
        environment: s.environment ?? 'prod',
      }))
      setSubscriptions(normalised)
    } catch {
      setError('Failed to load subscriptions')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchSubscriptions() }, [])

  return (
    <div className="space-y-4">
      <InfoBanner />

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-medium text-[var(--text-primary)]">
            Monitored Subscriptions
          </h3>
          {!loading && (
            <Badge variant="secondary" className="text-xs">
              {subscriptions.length}
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={fetchSubscriptions}
            disabled={loading}
            title="Refresh"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          </Button>
          <Button
            size="sm"
            onClick={() => setShowAddDrawer(true)}
            className="bg-[var(--accent-blue)] text-white hover:opacity-90"
          >
            <Plus className="h-4 w-4 mr-1" />
            Add
          </Button>
        </div>
      </div>

      {error && (
        <p className="text-sm text-[var(--accent-red)]">{error}</p>
      )}

      {loading ? (
        <div className="space-y-2">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-12 rounded bg-[var(--bg-surface)] animate-pulse" />
          ))}
        </div>
      ) : subscriptions.length === 0 ? (
        <div className="rounded-lg border border-dashed border-[var(--border)] p-8 text-center text-sm text-[var(--text-secondary)]">
          No subscriptions onboarded yet. Click &quot;+ Add&quot; to get started.
        </div>
      ) : (
        <div className="rounded-lg border border-[var(--border)] overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-[var(--bg-surface)]">
              <tr>
                <th className="px-3 py-2 text-left font-medium text-[var(--text-secondary)]">Name</th>
                <th className="px-3 py-2 text-left font-medium text-[var(--text-secondary)]">Subscription ID</th>
                <th className="px-3 py-2 text-left font-medium text-[var(--text-secondary)]">Credential</th>
                <th className="px-3 py-2 text-left font-medium text-[var(--text-secondary)]">Permissions</th>
                <th className="px-3 py-2 text-left font-medium text-[var(--text-secondary)]">Secret Expiry</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border)]">
              {subscriptions.map((sub) => (
                <tr key={sub.subscription_id} className="hover:bg-[var(--bg-surface)] transition-colors">
                  <td className="px-3 py-2 font-medium text-[var(--text-primary)]">
                    {sub.display_name || sub.subscription_id}
                    {sub.environment && (
                      <span className="ml-1 text-xs text-[var(--text-secondary)]">
                        ({sub.environment})
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 font-mono text-xs text-[var(--text-secondary)]">
                    {sub.subscription_id}
                  </td>
                  <td className="px-3 py-2">
                    {sub.credential_type === 'spn' ? (
                      <Badge
                        style={{ background: 'color-mix(in srgb, var(--accent-blue) 15%, transparent)' }}
                        className="text-xs"
                      >
                        🔑 SPN
                      </Badge>
                    ) : (
                      <Badge
                        style={{ background: 'color-mix(in srgb, var(--accent-blue) 15%, transparent)' }}
                        className="text-xs"
                        title="Platform Managed Identity — re-onboard required"
                      >
                        🔵 Platform MI
                      </Badge>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-0.5">
                      {['reader', 'monitoring_reader', 'security_reader', 'cost_management_reader'].map((k) => (
                        <PermIcon key={k} status={sub.permission_status?.[k] ?? 'unknown'} />
                      ))}
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    <ExpiryBadge
                      daysUntilExpiry={sub.days_until_expiry}
                      secretExpiresAt={sub.secret_expires_at}
                    />
                  </td>
                  <td className="px-3 py-2">
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="sm" className="h-7 w-7 p-0">
                          <MoreHorizontal className="h-4 w-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onClick={async () => {
                          await fetch(`/api/proxy/subscriptions/onboard/${sub.subscription_id}/validate`, { method: 'POST' })
                          fetchSubscriptions()
                        }}>
                          Re-validate permissions
                        </DropdownMenuItem>
                        <DropdownMenuItem onClick={() => setUpdateTarget(sub.subscription_id)}>
                          Update credentials
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          className="text-[var(--accent-red)]"
                          onClick={async () => {
                            if (!confirm(`Remove monitoring for ${sub.display_name}? This cannot be undone.`)) return
                            try {
                              const res = await fetch(`/api/proxy/subscriptions/onboard/${sub.subscription_id}`, { method: 'DELETE' })
                              if (!res.ok) {
                                const body = await res.json().catch(() => ({}))
                                setError(body?.error ?? `Delete failed (HTTP ${res.status})`)
                                return
                              }
                            } catch {
                              setError('Failed to reach API gateway')
                              return
                            }
                            fetchSubscriptions()
                          }}
                        >
                          Remove subscription
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showAddDrawer && (
        <AddSubscriptionDrawerLazy
          open={showAddDrawer}
          onClose={() => setShowAddDrawer(false)}
          onSuccess={fetchSubscriptions}
        />
      )}
      {updateTarget && (
        <UpdateCredentialsDrawerLazy
          open={!!updateTarget}
          subscriptionId={updateTarget}
          onClose={() => setUpdateTarget(null)}
          onSuccess={fetchSubscriptions}
        />
      )}
    </div>
  )
}

// Lazy wrappers to avoid circular deps — these are dynamically imported after the component file is created
function AddSubscriptionDrawerLazy(props: { open: boolean; onClose: () => void; onSuccess: () => void }) {
  const [Comp, setComp] = useState<React.ComponentType<typeof props> | null>(null)
  useEffect(() => {
    import('./AddSubscriptionDrawer').then(m => setComp(() => m.AddSubscriptionDrawer))
  }, [])
  if (!Comp) return null
  return <Comp {...props} />
}

function UpdateCredentialsDrawerLazy(props: { open: boolean; subscriptionId: string; onClose: () => void; onSuccess: () => void }) {
  const [Comp, setComp] = useState<React.ComponentType<typeof props> | null>(null)
  useEffect(() => {
    import('./UpdateCredentialsDrawer').then(m => setComp(() => m.UpdateCredentialsDrawer))
  }, [])
  if (!Comp) return null
  return <Comp {...props} />
}
