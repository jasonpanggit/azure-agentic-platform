'use client'

import { useState, useEffect, useCallback } from 'react'
import { Plus, Pencil, Trash2, AlertCircle, Loader2, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Alert } from '@/components/ui/alert'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetFooter,
} from '@/components/ui/sheet'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'

// ─── Types ───────────────────────────────────────────────────────────────────

type ActionClass =
  | 'restart_vm'
  | 'deallocate_vm'
  | 'start_vm'
  | 'resize_vm'
  | 'restart_container_app'

interface TagFilter {
  key: string
  value: string
}

interface RemediationPolicy {
  id: string
  name: string
  description: string
  action_class: ActionClass
  resource_tag_filter: Record<string, string>
  max_blast_radius: number
  max_daily_executions: number
  require_slo_healthy: boolean
  maintenance_window_exempt: boolean
  enabled: boolean
  execution_count_today: number
  created_at: string
  updated_at: string
}

interface PolicySuggestion {
  id: string
  message: string
  action_class: ActionClass
  approval_count: number
  created_at: string
}

interface PolicyFormData {
  name: string
  description: string
  action_class: ActionClass
  tag_filters: TagFilter[]
  max_blast_radius: number
  max_daily_executions: number
  require_slo_healthy: boolean
  maintenance_window_exempt: boolean
  enabled: boolean
}

const DEFAULT_FORM: PolicyFormData = {
  name: '',
  description: '',
  action_class: 'restart_vm',
  tag_filters: [],
  max_blast_radius: 5,
  max_daily_executions: 10,
  require_slo_healthy: true,
  maintenance_window_exempt: false,
  enabled: true,
}

const ACTION_CLASS_OPTIONS: { value: ActionClass; label: string }[] = [
  { value: 'restart_vm', label: 'Restart VM' },
  { value: 'deallocate_vm', label: 'Deallocate VM' },
  { value: 'start_vm', label: 'Start VM' },
  { value: 'resize_vm', label: 'Resize VM' },
  { value: 'restart_container_app', label: 'Restart Container App' },
]

// ─── Helpers ──────────────────────────────────────────────────────────────────

function tagFiltersToRecord(filters: TagFilter[]): Record<string, string> {
  const record: Record<string, string> = {}
  for (const f of filters) {
    if (f.key.trim()) {
      record[f.key.trim()] = f.value.trim()
    }
  }
  return record
}

function recordToTagFilters(record: Record<string, string>): TagFilter[] {
  return Object.entries(record).map(([key, value]) => ({ key, value }))
}

function formatTagFilter(record: Record<string, string>): string {
  const entries = Object.entries(record)
  if (entries.length === 0) return '—'
  return entries.map(([k, v]) => `${k}=${v}`).join(', ')
}

// ─── PolicyForm ────────────────────────────────────────────────────────────────

interface PolicyFormProps {
  form: PolicyFormData
  onChange: (data: PolicyFormData) => void
  onSubmit: () => void
  onCancel: () => void
  submitting: boolean
  title: string
}

function PolicyForm({ form, onChange, onSubmit, onCancel, submitting, title }: PolicyFormProps) {
  function update<K extends keyof PolicyFormData>(key: K, value: PolicyFormData[K]) {
    onChange({ ...form, [key]: value })
  }

  function addTag() {
    onChange({ ...form, tag_filters: [...form.tag_filters, { key: '', value: '' }] })
  }

  function updateTag(index: number, field: 'key' | 'value', value: string) {
    const updated = form.tag_filters.map((t, i) => i === index ? { ...t, [field]: value } : t)
    onChange({ ...form, tag_filters: updated })
  }

  function removeTag(index: number) {
    onChange({ ...form, tag_filters: form.tag_filters.filter((_, i) => i !== index) })
  }

  return (
    <div className="flex flex-col h-full">
      <SheetHeader className="mb-6">
        <SheetTitle style={{ color: 'var(--text-primary)' }}>{title}</SheetTitle>
      </SheetHeader>

      <div className="flex-1 overflow-y-auto space-y-4 pr-1">
        {/* Name */}
        <div className="space-y-1">
          <label className="text-sm font-medium" style={{ color: 'var(--text-secondary)' }}>
            Name <span className="text-red-500">*</span>
          </label>
          <Input
            value={form.name}
            onChange={(e) => update('name', e.target.value)}
            placeholder="e.g. Auto-restart unhealthy VMs"
          />
        </div>

        {/* Description */}
        <div className="space-y-1">
          <label className="text-sm font-medium" style={{ color: 'var(--text-secondary)' }}>
            Description
          </label>
          <Textarea
            value={form.description}
            onChange={(e) => update('description', e.target.value)}
            placeholder="What does this policy do?"
            rows={2}
          />
        </div>

        {/* Action Class */}
        <div className="space-y-1">
          <label className="text-sm font-medium" style={{ color: 'var(--text-secondary)' }}>
            Action Class <span className="text-red-500">*</span>
          </label>
          <Select value={form.action_class} onValueChange={(v) => update('action_class', v as ActionClass)}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ACTION_CLASS_OPTIONS.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>
                  {opt.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Resource Tag Filters */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label className="text-sm font-medium" style={{ color: 'var(--text-secondary)' }}>
              Resource Tag Filter
            </label>
            <Button variant="ghost" size="sm" onClick={addTag} className="text-xs h-7 px-2">
              + Add Tag
            </Button>
          </div>
          {form.tag_filters.length === 0 && (
            <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
              No tag filters — policy applies to all resources.
            </p>
          )}
          {form.tag_filters.map((tag, i) => (
            <div key={i} className="flex items-center gap-2">
              <Input
                placeholder="key"
                value={tag.key}
                onChange={(e) => updateTag(i, 'key', e.target.value)}
                className="flex-1"
              />
              <span style={{ color: 'var(--text-secondary)' }}>=</span>
              <Input
                placeholder="value"
                value={tag.value}
                onChange={(e) => updateTag(i, 'value', e.target.value)}
                className="flex-1"
              />
              <button
                onClick={() => removeTag(i)}
                className="p-1 rounded hover:opacity-70"
                style={{ color: 'var(--text-secondary)' }}
                aria-label="Remove tag"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>

        {/* Max Blast Radius */}
        <div className="space-y-1">
          <label className="text-sm font-medium" style={{ color: 'var(--text-secondary)' }}>
            Max Blast Radius <span className="text-xs font-normal">(1–50 resources per run)</span>
          </label>
          <Input
            type="number"
            min={1}
            max={50}
            value={form.max_blast_radius}
            onChange={(e) => update('max_blast_radius', Math.min(50, Math.max(1, parseInt(e.target.value) || 1)))}
          />
        </div>

        {/* Max Daily Executions */}
        <div className="space-y-1">
          <label className="text-sm font-medium" style={{ color: 'var(--text-secondary)' }}>
            Max Daily Executions <span className="text-xs font-normal">(1–100)</span>
          </label>
          <Input
            type="number"
            min={1}
            max={100}
            value={form.max_daily_executions}
            onChange={(e) => update('max_daily_executions', Math.min(100, Math.max(1, parseInt(e.target.value) || 1)))}
          />
        </div>

        {/* Toggles */}
        <div className="space-y-3 pt-1">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>Require SLO Healthy</p>
              <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>Only execute when SLO is within budget</p>
            </div>
            <Switch
              checked={form.require_slo_healthy}
              onCheckedChange={(checked) => update('require_slo_healthy', checked)}
            />
          </div>

          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>Maintenance Window Exempt</p>
              <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>Run even during maintenance windows</p>
            </div>
            <Switch
              checked={form.maintenance_window_exempt}
              onCheckedChange={(checked) => update('maintenance_window_exempt', checked)}
            />
          </div>

          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>Enabled</p>
              <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>Allow this policy to trigger automatically</p>
            </div>
            <Switch
              checked={form.enabled}
              onCheckedChange={(checked) => update('enabled', checked)}
            />
          </div>
        </div>
      </div>

      <SheetFooter className="mt-6 flex gap-2">
        <Button variant="outline" onClick={onCancel} disabled={submitting}>
          Cancel
        </Button>
        <Button
          onClick={onSubmit}
          disabled={submitting || !form.name.trim()}
          style={{ background: 'var(--accent-blue)', color: '#fff' }}
        >
          {submitting ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
          Save Policy
        </Button>
      </SheetFooter>
    </div>
  )
}

// ─── PolicyListPanel ──────────────────────────────────────────────────────────

function PolicyListPanel() {
  const [policies, setPolicies] = useState<RemediationPolicy[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [sheetOpen, setSheetOpen] = useState(false)
  const [editingPolicy, setEditingPolicy] = useState<RemediationPolicy | null>(null)
  const [formData, setFormData] = useState<PolicyFormData>(DEFAULT_FORM)
  const [submitting, setSubmitting] = useState(false)
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null)

  const fetchPolicies = useCallback(async () => {
    try {
      setLoading(true)
      setError(null)
      const res = await fetch('/api/proxy/admin/remediation-policies')
      if (!res.ok) {
        const data = await res.json()
        throw new Error(data.error ?? `HTTP ${res.status}`)
      }
      const data = await res.json()
      setPolicies(Array.isArray(data) ? data : (data.policies ?? []))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load policies')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchPolicies() }, [fetchPolicies])

  function openCreate() {
    setEditingPolicy(null)
    setFormData(DEFAULT_FORM)
    setSheetOpen(true)
  }

  function openEdit(policy: RemediationPolicy) {
    setEditingPolicy(policy)
    setFormData({
      name: policy.name,
      description: policy.description,
      action_class: policy.action_class,
      tag_filters: recordToTagFilters(policy.resource_tag_filter),
      max_blast_radius: policy.max_blast_radius,
      max_daily_executions: policy.max_daily_executions,
      require_slo_healthy: policy.require_slo_healthy,
      maintenance_window_exempt: policy.maintenance_window_exempt,
      enabled: policy.enabled,
    })
    setSheetOpen(true)
  }

  async function handleSubmit() {
    setSubmitting(true)
    try {
      const payload = {
        name: formData.name,
        description: formData.description,
        action_class: formData.action_class,
        resource_tag_filter: tagFiltersToRecord(formData.tag_filters),
        max_blast_radius: formData.max_blast_radius,
        max_daily_executions: formData.max_daily_executions,
        require_slo_healthy: formData.require_slo_healthy,
        maintenance_window_exempt: formData.maintenance_window_exempt,
        enabled: formData.enabled,
      }

      if (editingPolicy) {
        const res = await fetch(`/api/proxy/admin/remediation-policies/${editingPolicy.id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        })
        if (!res.ok) {
          const data = await res.json()
          throw new Error(data.error ?? `HTTP ${res.status}`)
        }
        const updated = await res.json()
        setPolicies((prev) => prev.map((p) => p.id === editingPolicy.id ? updated : p))
      } else {
        const res = await fetch('/api/proxy/admin/remediation-policies', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        })
        if (!res.ok) {
          const data = await res.json()
          throw new Error(data.error ?? `HTTP ${res.status}`)
        }
        const created = await res.json()
        setPolicies((prev) => [...prev, created])
      }
      setSheetOpen(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save policy')
    } finally {
      setSubmitting(false)
    }
  }

  async function handleToggleEnabled(policy: RemediationPolicy) {
    // Optimistic update
    const updated = { ...policy, enabled: !policy.enabled }
    setPolicies((prev) => prev.map((p) => p.id === policy.id ? updated : p))
    try {
      const res = await fetch(`/api/proxy/admin/remediation-policies/${policy.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...policy, enabled: !policy.enabled }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
    } catch {
      // Revert on error
      setPolicies((prev) => prev.map((p) => p.id === policy.id ? policy : p))
    }
  }

  async function handleDelete(id: string) {
    // Optimistic update
    const previous = policies
    setPolicies((prev) => prev.filter((p) => p.id !== id))
    setDeleteConfirmId(null)
    try {
      const res = await fetch(`/api/proxy/admin/remediation-policies/${id}`, { method: 'DELETE' })
      if (!res.ok && res.status !== 204) throw new Error(`HTTP ${res.status}`)
    } catch {
      // Revert on error
      setPolicies(previous)
    }
  }

  if (loading) {
    return (
      <div className="space-y-3 p-4">
        {[...Array(4)].map((_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {error && (
        <Alert variant="destructive" className="flex items-center gap-2">
          <AlertCircle className="h-4 w-4" />
          <span className="text-sm">{error}</span>
        </Alert>
      )}

      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
          Remediation Policies <span className="font-normal" style={{ color: 'var(--text-secondary)' }}>({policies.length})</span>
        </h3>
        <Button
          size="sm"
          onClick={openCreate}
          style={{ background: 'var(--accent-blue)', color: '#fff' }}
          className="flex items-center gap-1.5"
        >
          <Plus className="h-3.5 w-3.5" />
          Create Policy
        </Button>
      </div>

      {policies.length === 0 ? (
        <div
          className="text-center py-12 rounded-lg"
          style={{ border: '1px dashed var(--border)', color: 'var(--text-secondary)' }}
        >
          <p className="text-sm">No remediation policies configured.</p>
          <p className="text-xs mt-1">Create your first policy to enable autonomous remediation.</p>
        </div>
      ) : (
        <div className="rounded-lg overflow-hidden" style={{ border: '1px solid var(--border)' }}>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Action Class</TableHead>
                <TableHead>Tag Filter</TableHead>
                <TableHead className="text-center">Blast Radius</TableHead>
                <TableHead className="text-center">Daily Cap</TableHead>
                <TableHead className="text-center">Enabled</TableHead>
                <TableHead className="text-center">Today</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {policies.map((policy) => (
                <TableRow key={policy.id}>
                  <TableCell>
                    <div>
                      <p className="font-medium text-sm" style={{ color: 'var(--text-primary)' }}>{policy.name}</p>
                      {policy.description && (
                        <p className="text-xs mt-0.5 truncate max-w-[200px]" style={{ color: 'var(--text-secondary)' }}>{policy.description}</p>
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant="outline"
                      className="text-xs font-mono"
                      style={{
                        background: 'color-mix(in srgb, var(--accent-blue) 15%, transparent)',
                        borderColor: 'transparent',
                        color: 'var(--text-primary)',
                      }}
                    >
                      {policy.action_class}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <span className="text-xs font-mono" style={{ color: 'var(--text-secondary)' }}>
                      {formatTagFilter(policy.resource_tag_filter)}
                    </span>
                  </TableCell>
                  <TableCell className="text-center text-sm" style={{ color: 'var(--text-primary)' }}>
                    {policy.max_blast_radius}
                  </TableCell>
                  <TableCell className="text-center text-sm" style={{ color: 'var(--text-primary)' }}>
                    {policy.max_daily_executions}
                  </TableCell>
                  <TableCell className="text-center">
                    <Switch
                      checked={policy.enabled}
                      onCheckedChange={() => handleToggleEnabled(policy)}
                      aria-label={`Toggle ${policy.name} enabled`}
                    />
                  </TableCell>
                  <TableCell className="text-center">
                    <Badge
                      variant="outline"
                      className="text-xs"
                      style={{
                        background: policy.execution_count_today > 0
                          ? 'color-mix(in srgb, var(--accent-blue) 15%, transparent)'
                          : 'color-mix(in srgb, var(--accent-green) 15%, transparent)',
                        borderColor: 'transparent',
                        color: 'var(--text-primary)',
                      }}
                    >
                      {policy.execution_count_today ?? 0}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    {deleteConfirmId === policy.id ? (
                      <div className="flex items-center justify-end gap-1">
                        <span className="text-xs mr-1" style={{ color: 'var(--text-secondary)' }}>Delete?</span>
                        <Button
                          variant="destructive"
                          size="sm"
                          className="h-7 text-xs px-2"
                          onClick={() => handleDelete(policy.id)}
                        >
                          Yes
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-7 text-xs px-2"
                          onClick={() => setDeleteConfirmId(null)}
                        >
                          No
                        </Button>
                      </div>
                    ) : (
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7"
                          onClick={() => openEdit(policy)}
                          aria-label="Edit policy"
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 text-destructive hover:text-destructive"
                          onClick={() => setDeleteConfirmId(policy.id)}
                          aria-label="Delete policy"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
        <SheetContent side="right" className="w-full sm:max-w-lg overflow-y-auto flex flex-col">
          <PolicyForm
            form={formData}
            onChange={setFormData}
            onSubmit={handleSubmit}
            onCancel={() => setSheetOpen(false)}
            submitting={submitting}
            title={editingPolicy ? 'Edit Policy' : 'Create Policy'}
          />
        </SheetContent>
      </Sheet>
    </div>
  )
}

// ─── PolicySuggestionsPanel ───────────────────────────────────────────────────

function PolicySuggestionsPanel() {
  const [suggestions, setSuggestions] = useState<PolicySuggestion[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [sheetOpen, setSheetOpen] = useState(false)
  const [convertFormData, setConvertFormData] = useState<PolicyFormData>(DEFAULT_FORM)
  const [convertingSuggestionId, setConvertingSuggestionId] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const fetchSuggestions = useCallback(async () => {
    try {
      setLoading(true)
      setError(null)
      const res = await fetch('/api/proxy/admin/policy-suggestions')
      if (!res.ok) {
        const data = await res.json()
        throw new Error(data.error ?? `HTTP ${res.status}`)
      }
      const data = await res.json()
      setSuggestions(Array.isArray(data) ? data : (data.suggestions ?? []))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load suggestions')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchSuggestions() }, [fetchSuggestions])

  async function handleDismiss(id: string) {
    // Optimistic remove
    const previous = suggestions
    setSuggestions((prev) => prev.filter((s) => s.id !== id))
    try {
      const res = await fetch(`/api/proxy/admin/policy-suggestions/${id}/dismiss`, { method: 'POST' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
    } catch {
      setSuggestions(previous)
    }
  }

  function openConvert(suggestion: PolicySuggestion) {
    setConvertingSuggestionId(suggestion.id)
    setConvertFormData({
      ...DEFAULT_FORM,
      action_class: suggestion.action_class,
      name: `Auto: ${suggestion.action_class.replace(/_/g, ' ')}`,
    })
    setSheetOpen(true)
  }

  async function handleConvertSubmit() {
    if (!convertingSuggestionId) return
    setSubmitting(true)
    try {
      const payload = {
        name: convertFormData.name,
        description: convertFormData.description,
        action_class: convertFormData.action_class,
        resource_tag_filter: tagFiltersToRecord(convertFormData.tag_filters),
        max_blast_radius: convertFormData.max_blast_radius,
        max_daily_executions: convertFormData.max_daily_executions,
        require_slo_healthy: convertFormData.require_slo_healthy,
        maintenance_window_exempt: convertFormData.maintenance_window_exempt,
        enabled: convertFormData.enabled,
      }
      const res = await fetch(
        `/api/proxy/admin/policy-suggestions/${convertingSuggestionId}/convert`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        }
      )
      if (!res.ok) {
        const data = await res.json()
        throw new Error(data.error ?? `HTTP ${res.status}`)
      }
      // Remove the converted suggestion from the list
      setSuggestions((prev) => prev.filter((s) => s.id !== convertingSuggestionId))
      setSheetOpen(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to convert suggestion')
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return (
      <div className="space-y-3 p-4">
        {[...Array(3)].map((_, i) => (
          <Skeleton key={i} className="h-20 w-full" />
        ))}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {error && (
        <Alert variant="destructive" className="flex items-center gap-2">
          <AlertCircle className="h-4 w-4" />
          <span className="text-sm">{error}</span>
        </Alert>
      )}

      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
          Policy Suggestions <span className="font-normal" style={{ color: 'var(--text-secondary)' }}>({suggestions.length})</span>
        </h3>
      </div>

      {suggestions.length === 0 ? (
        <div
          className="text-center py-12 rounded-lg"
          style={{ border: '1px dashed var(--border)', color: 'var(--text-secondary)' }}
        >
          <p className="text-sm">No policy suggestions available.</p>
          <p className="text-xs mt-1">Suggestions are generated when repeated agent approvals are detected.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {suggestions.map((suggestion) => (
            <div
              key={suggestion.id}
              className="rounded-lg p-4"
              style={{
                background: 'var(--bg-surface)',
                border: '1px solid var(--border)',
              }}
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <p className="text-sm" style={{ color: 'var(--text-primary)' }}>
                    {suggestion.message}
                  </p>
                  <div className="flex items-center gap-2 mt-2">
                    <Badge
                      variant="outline"
                      className="text-xs font-mono"
                      style={{
                        background: 'color-mix(in srgb, var(--accent-blue) 15%, transparent)',
                        borderColor: 'transparent',
                        color: 'var(--text-primary)',
                      }}
                    >
                      {suggestion.action_class}
                    </Badge>
                    <Badge
                      variant="outline"
                      className="text-xs"
                      style={{
                        background: 'color-mix(in srgb, var(--accent-green) 15%, transparent)',
                        borderColor: 'transparent',
                        color: 'var(--text-primary)',
                      }}
                    >
                      {suggestion.approval_count} approval{suggestion.approval_count !== 1 ? 's' : ''}
                    </Badge>
                  </div>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  <Button
                    size="sm"
                    onClick={() => openConvert(suggestion)}
                    style={{ background: 'var(--accent-blue)', color: '#fff' }}
                    className="text-xs h-7 px-2"
                  >
                    Create Policy
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 px-2 text-xs"
                    style={{ color: 'var(--text-secondary)' }}
                    onClick={() => handleDismiss(suggestion.id)}
                  >
                    Dismiss
                  </Button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
        <SheetContent side="right" className="w-full sm:max-w-lg overflow-y-auto flex flex-col">
          <PolicyForm
            form={convertFormData}
            onChange={setConvertFormData}
            onSubmit={handleConvertSubmit}
            onCancel={() => setSheetOpen(false)}
            submitting={submitting}
            title="Create Policy from Suggestion"
          />
        </SheetContent>
      </Sheet>
    </div>
  )
}

// ─── SettingsTab (main export) ────────────────────────────────────────────────

type SettingsSubTab = 'policies' | 'suggestions'

export function SettingsTab() {
  const [subTab, setSubTab] = useState<SettingsSubTab>('policies')

  return (
    <div className="space-y-4">
      {/* Sub-tab selector */}
      <div
        className="flex items-center gap-1 p-1 rounded-lg w-fit"
        style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)' }}
        role="tablist"
        aria-label="Settings sections"
      >
        {(
          [
            { id: 'policies', label: 'Remediation Policies' },
            { id: 'suggestions', label: 'Policy Suggestions' },
          ] as { id: SettingsSubTab; label: string }[]
        ).map(({ id, label }) => {
          const isActive = subTab === id
          return (
            <button
              key={id}
              role="tab"
              aria-selected={isActive}
              onClick={() => setSubTab(id)}
              className="px-3 py-1.5 text-xs font-medium rounded-md transition-colors cursor-pointer"
              style={{
                background: isActive ? 'var(--bg-surface)' : 'transparent',
                color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
                fontWeight: isActive ? 600 : 400,
                boxShadow: isActive ? '0 1px 2px rgba(0,0,0,0.1)' : 'none',
              }}
            >
              {label}
            </button>
          )
        })}
      </div>

      {/* Panel content */}
      <div
        className="rounded-lg p-4"
        style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
      >
        {subTab === 'policies' ? <PolicyListPanel /> : <PolicySuggestionsPanel />}
      </div>
    </div>
  )
}
