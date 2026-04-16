'use client'

import React, { useEffect, useState, useCallback } from 'react'
import { useMsal } from '@azure/msal-react'
import { InteractionRequiredAuthError } from '@azure/msal-browser'
import { gatewayTokenRequest } from '@/lib/msal-config'
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
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Building2, RefreshCw, PlusCircle, Edit2 } from 'lucide-react'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Tenant {
  tenant_id: string
  name: string
  subscriptions: string[]
  sla_definitions: object[]
  compliance_frameworks: string[]
  operator_group_id: string
  created_at: string
}

interface TenantsResponse {
  tenants: Tenant[]
  total: number
}

// ---------------------------------------------------------------------------
// Compliance framework options
// ---------------------------------------------------------------------------

const COMPLIANCE_OPTIONS = ['SOC2', 'ISO27001', 'PCI-DSS', 'HIPAA', 'NIST', 'CIS', 'FedRAMP']

// ---------------------------------------------------------------------------
// StatusBadge — uses CSS semantic tokens
// ---------------------------------------------------------------------------

function FrameworkBadge({ label }: { label: string }) {
  return (
    <Badge
      style={{
        background: 'color-mix(in srgb, var(--accent-blue) 15%, transparent)',
        color: 'var(--accent-blue)',
        border: '1px solid color-mix(in srgb, var(--accent-blue) 30%, transparent)',
        marginRight: '4px',
        marginBottom: '2px',
      }}
    >
      {label}
    </Badge>
  )
}

// ---------------------------------------------------------------------------
// CreateTenantModal
// ---------------------------------------------------------------------------

interface CreateTenantModalProps {
  open: boolean
  onClose: () => void
  onCreated: () => void
}

function CreateTenantModal({ open, onClose, onCreated }: CreateTenantModalProps) {
  const { instance, accounts } = useMsal()
  const [name, setName] = useState('')
  const [operatorGroupId, setOperatorGroupId] = useState('')
  const [subscriptionsRaw, setSubscriptionsRaw] = useState('')
  const [selectedFrameworks, setSelectedFrameworks] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const getAccessToken = useCallback(async (): Promise<string | null> => {
    const account = accounts[0]
    if (!account) return null
    try {
      const result = await instance.acquireTokenSilent({ ...gatewayTokenRequest, account })
      return result.accessToken
    } catch (err) {
      if (err instanceof InteractionRequiredAuthError) {
        await instance.acquireTokenRedirect({ ...gatewayTokenRequest, account })
      }
      return null
    }
  }, [instance, accounts])

  function reset() {
    setName('')
    setOperatorGroupId('')
    setSubscriptionsRaw('')
    setSelectedFrameworks([])
    setError(null)
  }

  function toggleFramework(fw: string) {
    setSelectedFrameworks((prev) =>
      prev.includes(fw) ? prev.filter((f) => f !== fw) : [...prev, fw]
    )
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      const subscriptions = subscriptionsRaw
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)

      const payload = {
        name: name.trim(),
        operator_group_id: operatorGroupId.trim(),
        subscriptions,
        compliance_frameworks: selectedFrameworks,
        sla_definitions: [],
      }

      const token = await getAccessToken()
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (token) headers['Authorization'] = `Bearer ${token}`

      const res = await fetch('/api/proxy/admin/tenants', {
        method: 'POST',
        headers,
        body: JSON.stringify(payload),
      })

      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data?.error ?? `HTTP ${res.status}`)
      }

      reset()
      onCreated()
      onClose()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) { reset(); onClose() } }}>
      <DialogContent style={{ background: 'var(--bg-canvas)', color: 'var(--text-primary)' }}>
        <DialogHeader>
          <DialogTitle style={{ color: 'var(--text-primary)' }}>Create Tenant</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          {error && (
            <Alert style={{ background: 'color-mix(in srgb, var(--accent-red) 10%, transparent)', borderColor: 'var(--accent-red)' }}>
              <AlertDescription style={{ color: 'var(--accent-red)' }}>{error}</AlertDescription>
            </Alert>
          )}
          <div className="space-y-1">
            <label className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>
              Tenant Name *
            </label>
            <Input
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. platform-engineering"
              style={{ background: 'var(--bg-canvas)', color: 'var(--text-primary)', borderColor: 'var(--border)' }}
            />
          </div>
          <div className="space-y-1">
            <label className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>
              Operator Group ID (Entra Object ID) *
            </label>
            <Input
              required
              value={operatorGroupId}
              onChange={(e) => setOperatorGroupId(e.target.value)}
              placeholder="e.g. 00000000-0000-0000-0000-000000000000"
              style={{ background: 'var(--bg-canvas)', color: 'var(--text-primary)', borderColor: 'var(--border)' }}
            />
          </div>
          <div className="space-y-1">
            <label className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>
              Subscriptions (comma-separated)
            </label>
            <Input
              value={subscriptionsRaw}
              onChange={(e) => setSubscriptionsRaw(e.target.value)}
              placeholder="sub-aaa-111, sub-bbb-222"
              style={{ background: 'var(--bg-canvas)', color: 'var(--text-primary)', borderColor: 'var(--border)' }}
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>
              Compliance Frameworks
            </label>
            <div className="flex flex-wrap gap-2">
              {COMPLIANCE_OPTIONS.map((fw) => (
                <button
                  key={fw}
                  type="button"
                  onClick={() => toggleFramework(fw)}
                  style={{
                    padding: '4px 10px',
                    borderRadius: '9999px',
                    fontSize: '0.75rem',
                    border: `1px solid ${selectedFrameworks.includes(fw) ? 'var(--accent-blue)' : 'var(--border)'}`,
                    background: selectedFrameworks.includes(fw)
                      ? 'color-mix(in srgb, var(--accent-blue) 20%, transparent)'
                      : 'transparent',
                    color: selectedFrameworks.includes(fw) ? 'var(--accent-blue)' : 'var(--text-primary)',
                    cursor: 'pointer',
                  }}
                >
                  {fw}
                </button>
              ))}
            </div>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => { reset(); onClose() }}
              disabled={submitting}
              style={{ borderColor: 'var(--border)', color: 'var(--text-primary)' }}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={submitting}
              style={{ background: 'var(--accent-blue)', color: '#fff' }}
            >
              {submitting ? 'Creating…' : 'Create Tenant'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// ---------------------------------------------------------------------------
// EditSubscriptionsInline
// ---------------------------------------------------------------------------

interface EditSubscriptionsProps {
  tenant: Tenant
  onSaved: () => void
}

function EditSubscriptionsInline({ tenant, onSaved }: EditSubscriptionsProps) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(tenant.subscriptions.join(', '))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSave() {
    setSaving(true)
    setError(null)
    try {
      const subs = value
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)

      const res = await fetch(`/api/proxy/admin/tenants/${tenant.tenant_id}/subscriptions`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ subscriptions: subs }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data?.error ?? `HTTP ${res.status}`)
      }
      setEditing(false)
      onSaved()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  if (!editing) {
    return (
      <div className="flex items-center gap-2">
        <span style={{ color: 'var(--text-primary)', fontSize: '0.85rem' }}>
          {tenant.subscriptions.length > 0
            ? tenant.subscriptions.join(', ')
            : <span style={{ color: 'var(--text-secondary, #888)' }}>none</span>}
        </span>
        <button
          onClick={() => setEditing(true)}
          title="Edit subscriptions"
          style={{ color: 'var(--accent-blue)', background: 'none', border: 'none', cursor: 'pointer' }}
        >
          <Edit2 size={13} />
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-1">
      <Input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        style={{ background: 'var(--bg-canvas)', color: 'var(--text-primary)', borderColor: 'var(--border)', fontSize: '0.8rem' }}
      />
      {error && <span style={{ color: 'var(--accent-red)', fontSize: '0.75rem' }}>{error}</span>}
      <div className="flex gap-2">
        <Button
          size="sm"
          disabled={saving}
          onClick={handleSave}
          style={{ background: 'var(--accent-blue)', color: '#fff', fontSize: '0.75rem' }}
        >
          {saving ? 'Saving…' : 'Save'}
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => { setEditing(false); setError(null) }}
          style={{ borderColor: 'var(--border)', color: 'var(--text-primary)', fontSize: '0.75rem' }}
        >
          Cancel
        </Button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// TenantAdminTab — main component
// ---------------------------------------------------------------------------

export function TenantAdminTab() {
  const { instance, accounts } = useMsal()
  const [tenants, setTenants] = useState<Tenant[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [createOpen, setCreateOpen] = useState(false)

  const getAccessToken = useCallback(async (): Promise<string | null> => {
    const account = accounts[0]
    if (!account) return null
    try {
      const result = await instance.acquireTokenSilent({ ...gatewayTokenRequest, account })
      return result.accessToken
    } catch (err) {
      if (err instanceof InteractionRequiredAuthError) {
        await instance.acquireTokenRedirect({ ...gatewayTokenRequest, account })
      }
      return null
    }
  }, [instance, accounts])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const token = await getAccessToken()
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`
      const res = await fetch('/api/proxy/admin/tenants', { headers })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data?.error ?? `HTTP ${res.status}`)
      }
      const data: TenantsResponse = await res.json()
      setTenants(data.tenants ?? [])
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load tenants')
    } finally {
      setLoading(false)
    }
  }, [getAccessToken])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <div className="space-y-4 p-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Building2 size={20} style={{ color: 'var(--accent-blue)' }} />
          <h2 className="text-lg font-semibold" style={{ color: 'var(--text-primary)' }}>
            Tenant Management
          </h2>
          <Badge
            style={{
              background: 'color-mix(in srgb, var(--accent-blue) 15%, transparent)',
              color: 'var(--accent-blue)',
              border: '1px solid color-mix(in srgb, var(--accent-blue) 30%, transparent)',
            }}
          >
            {tenants.length} tenant{tenants.length !== 1 ? 's' : ''}
          </Badge>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => void load()}
            disabled={loading}
            style={{ borderColor: 'var(--border)', color: 'var(--text-primary)' }}
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          </Button>
          <Button
            size="sm"
            onClick={() => setCreateOpen(true)}
            style={{ background: 'var(--accent-blue)', color: '#fff' }}
          >
            <PlusCircle size={14} className="mr-1" />
            Create Tenant
          </Button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <Alert style={{ background: 'color-mix(in srgb, var(--accent-red) 10%, transparent)', borderColor: 'var(--accent-red)' }}>
          <AlertDescription style={{ color: 'var(--accent-red)' }}>{error}</AlertDescription>
        </Alert>
      )}

      {/* Table */}
      <Card style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border)' }}>
        <CardContent className="p-0">
          {loading ? (
            <div className="p-6 space-y-3">
              {[1, 2, 3].map((i) => <Skeleton key={i} className="h-10 w-full" />)}
            </div>
          ) : tenants.length === 0 ? (
            <div
              className="flex flex-col items-center justify-center py-16 gap-3"
              style={{ color: 'var(--text-primary)' }}
            >
              <Building2 size={40} style={{ opacity: 0.3 }} />
              <p className="text-sm" style={{ opacity: 0.6 }}>
                No tenants configured — create one to enable multi-tenant isolation
              </p>
              <Button
                size="sm"
                onClick={() => setCreateOpen(true)}
                style={{ background: 'var(--accent-blue)', color: '#fff' }}
              >
                <PlusCircle size={14} className="mr-1" />
                Create Tenant
              </Button>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow style={{ borderColor: 'var(--border)' }}>
                  {['Name', 'Subscriptions', 'Compliance Frameworks', 'Operator Group', 'Created'].map((h) => (
                    <TableHead key={h} style={{ color: 'var(--text-primary)', fontWeight: 600 }}>
                      {h}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {tenants.map((t) => (
                  <TableRow key={t.tenant_id} style={{ borderColor: 'var(--border)' }}>
                    <TableCell style={{ color: 'var(--text-primary)', fontWeight: 500 }}>
                      {t.name}
                    </TableCell>
                    <TableCell>
                      <EditSubscriptionsInline tenant={t} onSaved={() => void load()} />
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap">
                        {t.compliance_frameworks.length > 0
                          ? t.compliance_frameworks.map((fw) => (
                              <FrameworkBadge key={fw} label={fw} />
                            ))
                          : <span style={{ color: 'var(--text-secondary, #888)', fontSize: '0.8rem' }}>none</span>}
                      </div>
                    </TableCell>
                    <TableCell style={{ color: 'var(--text-primary)', fontSize: '0.8rem', fontFamily: 'monospace' }}>
                      {t.operator_group_id}
                    </TableCell>
                    <TableCell style={{ color: 'var(--text-primary)', fontSize: '0.8rem' }}>
                      {new Date(t.created_at).toLocaleDateString()}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Create modal */}
      <CreateTenantModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={() => void load()}
      />
    </div>
  )
}
