'use client'

import React, { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Badge } from '@/components/ui/badge'
import { Loader2 } from 'lucide-react'

interface AddSubscriptionDrawerProps {
  open: boolean
  onClose: () => void
  onSuccess: () => void
}

interface PermissionStatus {
  reader?: string
  monitoring_reader?: string
  security_reader?: string
  cost_management_reader?: string
  vm_contributor?: string
  aks_contributor?: string
  container_apps_contributor?: string
}

const PERM_LABELS: Record<string, string> = {
  reader: 'Reader',
  monitoring_reader: 'Monitoring Reader',
  security_reader: 'Security Reader',
  cost_management_reader: 'Cost Management Reader',
  vm_contributor: 'VM Contributor',
  aks_contributor: 'AKS Contributor',
  container_apps_contributor: 'Container Apps Contributor',
}

export function AddSubscriptionDrawer({ open, onClose, onSuccess }: AddSubscriptionDrawerProps) {
  const [form, setForm] = useState({
    subscription_id: '',
    display_name: '',
    tenant_id: '',
    client_id: '',
    client_secret: '',
    secret_expires_at: '',
    environment: 'prod',
  })
  const [validating, setValidating] = useState(false)
  const [saving, setSaving] = useState(false)
  const [permStatus, setPermStatus] = useState<PermissionStatus | null>(null)
  const [validateError, setValidateError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [readerGranted, setReaderGranted] = useState(false)

  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm(f => ({ ...f, [k]: e.target.value }))

  const handleValidate = async () => {
    setValidating(true)
    setValidateError(null)
    setPermStatus(null)
    setReaderGranted(false)
    try {
      const resp = await fetch('/api/proxy/subscriptions/onboard/preview-validate', {
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
      const resp = await fetch('/api/proxy/subscriptions/onboard', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      })
      const data = await resp.json()
      if (!resp.ok) {
        setSaveError(data?.detail?.error ?? 'Onboard failed')
        return
      }
      onSuccess()
      onClose()
      setForm({ subscription_id: '', display_name: '', tenant_id: '', client_id: '', client_secret: '', secret_expires_at: '', environment: 'prod' })
      setPermStatus(null)
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
          <SheetTitle>Add Subscription</SheetTitle>
        </SheetHeader>

        <div className="mt-6 space-y-4">
          <div>
            <label htmlFor="sub-id" className="block text-sm font-medium mb-1">Subscription ID *</label>
            <Input id="sub-id" aria-label="Subscription ID" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" value={form.subscription_id} onChange={set('subscription_id')} />
          </div>
          <div>
            <label htmlFor="display-name" className="block text-sm font-medium mb-1">Display Name</label>
            <Input id="display-name" aria-label="Display Name" placeholder="e.g. Production - APAC" value={form.display_name} onChange={set('display_name')} />
          </div>
          <div>
            <label htmlFor="tenant-id" className="block text-sm font-medium mb-1">Tenant ID *</label>
            <Input id="tenant-id" aria-label="Tenant ID" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" value={form.tenant_id} onChange={set('tenant_id')} />
          </div>
          <div>
            <label htmlFor="client-id" className="block text-sm font-medium mb-1">Client ID *</label>
            <Input id="client-id" aria-label="Client ID" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" value={form.client_id} onChange={set('client_id')} />
          </div>
          <div>
            <label htmlFor="client-secret" className="block text-sm font-medium mb-1">Client Secret *</label>
            <Input id="client-secret" aria-label="Client Secret" type="password" placeholder="App Registration client secret" value={form.client_secret} onChange={set('client_secret')} />
          </div>
          <div>
            <label htmlFor="secret-expiry" className="block text-sm font-medium mb-1">Secret Expiry Date</label>
            <Input id="secret-expiry" aria-label="Secret Expiry Date" type="date" value={form.secret_expires_at} onChange={set('secret_expires_at')} />
            {!form.secret_expires_at && (
              <p className="text-xs text-yellow-600 mt-1">⚠️ No expiry set — add one to enable expiry alerts</p>
            )}
          </div>
          <div>
            <label htmlFor="environment" className="block text-sm font-medium mb-1">Environment</label>
            <select id="environment" aria-label="Environment" className="w-full rounded border border-[var(--border)] p-2 text-sm bg-[var(--bg-canvas)]" value={form.environment} onChange={set('environment')}>
              <option value="prod">Production</option>
              <option value="staging">Staging</option>
              <option value="dev">Development</option>
            </select>
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
              {!readerGranted && (
                <p className="text-xs text-[var(--accent-red)] mt-2">⛔ Reader permission is required — cannot save until granted.</p>
              )}
              {readerGranted && (
                <p className="text-xs text-[var(--accent-green)] mt-2">Some permissions may still be propagating (2-5 min) — re-validate after saving if needed.</p>
              )}
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
              disabled={!readerGranted || saving}
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
