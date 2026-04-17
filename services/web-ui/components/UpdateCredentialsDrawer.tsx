'use client'

import React, { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Badge } from '@/components/ui/badge'
import { Loader2 } from 'lucide-react'

interface UpdateCredentialsDrawerProps {
  open: boolean
  subscriptionId: string
  onClose: () => void
  onSuccess: () => void
}

interface PermissionStatus {
  reader?: string
  monitoring_reader?: string
  security_reader?: string
  cost_management_reader?: string
}

const PERM_LABELS: Record<string, string> = {
  reader: 'Reader',
  monitoring_reader: 'Monitoring Reader',
  security_reader: 'Security Reader',
  cost_management_reader: 'Cost Management Reader',
}

export function UpdateCredentialsDrawer({ open, subscriptionId, onClose, onSuccess }: UpdateCredentialsDrawerProps) {
  const [form, setForm] = useState({
    client_id: '',
    client_secret: '',
    secret_expires_at: '',
    tenant_id: '',
  })
  const [validating, setValidating] = useState(false)
  const [saving, setSaving] = useState(false)
  const [permStatus, setPermStatus] = useState<PermissionStatus | null>(null)
  const [validateError, setValidateError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [readerGranted, setReaderGranted] = useState(false)

  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm(f => ({ ...f, [k]: e.target.value }))

  const handleValidate = async () => {
    setValidating(true)
    setValidateError(null)
    setPermStatus(null)
    setReaderGranted(false)
    try {
      const resp = await fetch(`/api/proxy/subscriptions/onboard/${subscriptionId}/validate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      })
      const data = await resp.json()
      if (!resp.ok) {
        setValidateError(data?.detail?.error ?? 'Validation failed')
        return
      }
      setPermStatus(data.permission_status)
      setReaderGranted(data.permission_status?.reader === 'granted')
    } catch {
      setValidateError('Network error — check API connectivity')
    } finally {
      setValidating(false)
    }
  }

  const handleSave = async () => {
    setSaving(true)
    setSaveError(null)
    try {
      const resp = await fetch(`/api/proxy/subscriptions/onboard/${subscriptionId}/credentials`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      })
      const data = await resp.json()
      if (!resp.ok) {
        setSaveError(data?.detail?.error ?? 'Update failed')
        return
      }
      onSuccess()
      onClose()
    } catch {
      setSaveError('Network error — check API connectivity')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Sheet open={open} onOpenChange={v => !v && onClose()}>
      <SheetContent className="w-[480px] overflow-y-auto">
        <SheetHeader>
          <SheetTitle>Update Credentials</SheetTitle>
        </SheetHeader>

        <div className="mt-6 space-y-4">
          <div>
            <label className="block text-sm font-medium mb-1">Subscription ID</label>
            <p className="text-sm font-mono text-[var(--text-secondary)] bg-[var(--bg-surface)] rounded p-2">
              {subscriptionId}
            </p>
          </div>
          <div>
            <label htmlFor="upd-tenant-id" className="block text-sm font-medium mb-1">Tenant ID</label>
            <Input id="upd-tenant-id" aria-label="Tenant ID" placeholder="Leave blank to keep existing" value={form.tenant_id} onChange={set('tenant_id')} />
          </div>
          <div>
            <label htmlFor="upd-client-id" className="block text-sm font-medium mb-1">Client ID</label>
            <Input id="upd-client-id" aria-label="Client ID" placeholder="Leave blank to keep existing" value={form.client_id} onChange={set('client_id')} />
          </div>
          <div>
            <label htmlFor="upd-client-secret" className="block text-sm font-medium mb-1">Client Secret</label>
            <Input id="upd-client-secret" aria-label="Client Secret" type="password" placeholder="••••••••• — enter new secret to rotate" value={form.client_secret} onChange={set('client_secret')} />
          </div>
          <div>
            <label htmlFor="upd-secret-expiry" className="block text-sm font-medium mb-1">New Secret Expiry Date</label>
            <Input id="upd-secret-expiry" aria-label="Secret Expiry Date" type="date" value={form.secret_expires_at} onChange={set('secret_expires_at')} />
          </div>

          {validateError && (
            <p className="text-sm text-[var(--accent-red)] rounded border border-[var(--accent-red)] p-2">{validateError}</p>
          )}

          {permStatus && (
            <div className="rounded border border-[var(--border)] p-3 space-y-1">
              <p className="text-xs font-medium text-[var(--text-secondary)] mb-2">Permission Check Results</p>
              {Object.entries(PERM_LABELS).map(([key, label]) => {
                const status = permStatus[key as keyof PermissionStatus] ?? 'unknown'
                return (
                  <div key={key} className="flex items-center justify-between text-sm">
                    <span>{label}</span>
                    <Badge style={{ background: status === 'granted' ? 'color-mix(in srgb, var(--accent-green) 15%, transparent)' : 'color-mix(in srgb, var(--accent-yellow) 15%, transparent)' }} className="text-xs">
                      {status === 'granted' ? '✅ Granted' : `⚠️ ${status}`}
                    </Badge>
                  </div>
                )
              })}
            </div>
          )}

          {saveError && (
            <p className="text-sm text-[var(--accent-red)] rounded border border-[var(--accent-red)] p-2">{saveError}</p>
          )}

          <div className="flex gap-2 pt-2">
            <Button variant="outline" className="flex-1" onClick={handleValidate} disabled={validating}>
              {validating ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : null}
              Validate
            </Button>
            <Button
              className="flex-1 bg-[var(--accent-blue)] text-white hover:opacity-90"
              onClick={handleSave}
              disabled={saving}
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : null}
              Save
            </Button>
          </div>
          <Button variant="ghost" className="w-full" onClick={onClose}>Cancel</Button>
        </div>
      </SheetContent>
    </Sheet>
  )
}
