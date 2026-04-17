'use client'

import { useState, useEffect } from 'react'
import {
  LayoutDashboard, Bell, Network, Server, ShieldCheck,
  DollarSign, GitBranch, Wrench, ClipboardList, Settings,
  Building2,
} from 'lucide-react'
import { AlertFeed } from './AlertFeed'
import { AlertFilters } from './AlertFilters'
import { OpsTab } from './OpsTab'
import { VMDetailPanel } from './VMDetailPanel'
import { VMSSDetailPanel } from './VMSSDetailPanel'
import { AKSDetailPanel } from './AKSDetailPanel'
import { ResourcesHubTab } from './ResourcesHubTab'
import { NetworkHubTab } from './NetworkHubTab'
import { SecurityHubTab } from './SecurityHubTab'
import { CostHubTab } from './CostHubTab'
import { ChangeHubTab } from './ChangeHubTab'
import { OperationsHubTab } from './OperationsHubTab'
import { AuditHubTab } from './AuditHubTab'
import { AdminHubTab } from './AdminHubTab'
import { useAppState } from '@/lib/app-state-context'

// ─── Tab types ───────────────────────────────────────────────────────────────

type TabId =
  | 'dashboard'
  | 'alerts'
  | 'resources'
  | 'network'
  | 'security'
  | 'cost'
  | 'change'
  | 'operations'
  | 'audit'
  | 'admin'

interface FilterState {
  severity?: string
  domain?: string
  status?: string
}

interface TabDef {
  id: TabId
  label: string
  Icon: React.FC<{ className?: string }>
}

// ─── Top-level navigation ────────────────────────────────────────────────────
// 10 purposeful top-level tabs. Each hub tab owns internal sub-navigation.

const TAB_GROUPS: TabDef[][] = [
  // Primary AIOps workflow
  [
    { id: 'dashboard',  label: 'Dashboard',  Icon: LayoutDashboard },
    { id: 'alerts',     label: 'Alerts',     Icon: Bell },
    { id: 'resources',  label: 'Resources',  Icon: Server },
    { id: 'network',    label: 'Network',    Icon: Network },
  ],
  // Security / cost / change
  [
    { id: 'security',   label: 'Security',   Icon: ShieldCheck },
    { id: 'cost',       label: 'Cost',       Icon: DollarSign },
    { id: 'change',     label: 'Change',     Icon: GitBranch },
    { id: 'operations', label: 'Operations', Icon: Wrench },
  ],
  // Audit / admin
  [
    { id: 'audit',      label: 'Audit',      Icon: ClipboardList },
    { id: 'admin',      label: 'Admin',      Icon: Building2 },
  ],
]

const TABS: TabDef[] = TAB_GROUPS.flat()

// ─── Props ───────────────────────────────────────────────────────────────────

interface DashboardPanelProps {
  onTabChange?: (tab: TabId) => void
  onRegisterNavToAlerts?: (fn: () => void) => void
}

// ─── Component ───────────────────────────────────────────────────────────────

export function DashboardPanel({ onTabChange, onRegisterNavToAlerts }: DashboardPanelProps) {
  const [activeTab, setActiveTab] = useState<TabId>('dashboard')
  const [filters, setFilters] = useState<FilterState>({})
  const { selectedSubscriptions, selectedIncidentId } = useAppState()

  // VM detail panel
  const [vmDetailOpen, setVMDetailOpen] = useState(false)
  const [selectedVM, setSelectedVM] = useState<{
    incidentId: string | null
    resourceId: string | null
    resourceName: string | null
  } | null>(null)

  function openVMDetail(incidentId: string | null, resourceId: string | null, resourceName: string | null) {
    setSelectedVM({ incidentId, resourceId, resourceName })
    setVMDetailOpen(true)
  }
  function closeVMDetail() { setVMDetailOpen(false); setSelectedVM(null) }

  // VMSS detail panel
  const [vmssDetailOpen, setVMSSDetailOpen] = useState(false)
  const [selectedVMSS, setSelectedVMSS] = useState<{ resourceId: string; resourceName: string } | null>(null)

  function openVMSSDetail(resourceId: string, resourceName: string) {
    setSelectedVMSS({ resourceId, resourceName }); setVMSSDetailOpen(true)
  }
  function closeVMSSDetail() { setVMSSDetailOpen(false); setSelectedVMSS(null) }

  // AKS detail panel
  const [aksDetailOpen, setAKSDetailOpen] = useState(false)
  const [selectedAKS, setSelectedAKS] = useState<{ resourceId: string; resourceName: string } | null>(null)

  function openAKSDetail(resourceId: string, resourceName: string) {
    setSelectedAKS({ resourceId, resourceName }); setAKSDetailOpen(true)
  }
  function closeAKSDetail() { setAKSDetailOpen(false); setSelectedAKS(null) }

  function handleTabChange(tab: TabId) {
    setVMDetailOpen(false); setSelectedVM(null)
    setVMSSDetailOpen(false); setSelectedVMSS(null)
    setAKSDetailOpen(false); setSelectedAKS(null)
    setActiveTab(tab)
    onTabChange?.(tab)
  }

  useEffect(() => {
    onRegisterNavToAlerts?.(() => handleTabChange('alerts'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function handleTabKeyDown(e: React.KeyboardEvent, index: number) {
    if (e.key === 'ArrowRight') {
      e.preventDefault()
      const next = (index + 1) % TABS.length
      handleTabChange(TABS[next].id)
      document.getElementById(`tab-${TABS[next].id}`)?.focus()
    } else if (e.key === 'ArrowLeft') {
      e.preventDefault()
      const prev = (index - 1 + TABS.length) % TABS.length
      handleTabChange(TABS[prev].id)
      document.getElementById(`tab-${TABS[prev].id}`)?.focus()
    }
  }

  return (
    <div className="flex flex-col h-full overflow-hidden" style={{ background: 'var(--bg-canvas)' }}>
      {/* ── Top nav tab bar ──────────────────────────────────────────────── */}
      <div
        className="flex items-end shrink-0 relative z-[35] overflow-x-auto [&::-webkit-scrollbar]:hidden"
        role="tablist"
        aria-label="Dashboard sections"
        style={{
          background: 'var(--bg-surface)',
          borderBottom: '1px solid var(--border)',
          scrollbarWidth: 'none',
        }}
      >
        {TAB_GROUPS.map((group, groupIdx) => (
          <div key={groupIdx} className="flex items-end shrink-0">
            {group.map(({ id, label, Icon }) => {
              const index = TABS.findIndex(t => t.id === id)
              const isActive = activeTab === id
              return (
                <button
                  key={id}
                  id={`tab-${id}`}
                  role="tab"
                  aria-selected={isActive}
                  aria-controls={`tabpanel-${id}`}
                  onClick={() => handleTabChange(id)}
                  onKeyDown={(e) => handleTabKeyDown(e, index)}
                  className="flex items-center gap-1.5 px-4 py-3 text-[13px] transition-colors outline-none relative whitespace-nowrap shrink-0 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500/60 cursor-pointer"
                  style={{
                    color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
                    fontWeight: isActive ? 600 : 500,
                    borderBottom: isActive ? '2px solid var(--accent-blue)' : '2px solid transparent',
                    marginBottom: '-1px',
                    background: 'transparent',
                  }}
                  onMouseEnter={(e) => { if (!isActive) e.currentTarget.style.background = 'var(--bg-subtle)' }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}
                >
                  <Icon className="h-3.5 w-3.5" />
                  {label}
                </button>
              )
            })}
            {groupIdx < TAB_GROUPS.length - 1 && (
              <div
                className="self-center mx-1 shrink-0"
                style={{ width: 1, height: 16, background: 'var(--border)' }}
                aria-hidden="true"
              />
            )}
          </div>
        ))}
      </div>

      {/* ── Tab panels ───────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-auto p-6">

        {/* Dashboard — platform health, agent status, SLA, quality */}
        <div id="tabpanel-dashboard" role="tabpanel" aria-labelledby="tab-dashboard" hidden={activeTab !== 'dashboard'}>
          <OpsTab subscriptions={selectedSubscriptions} onNavigateToAlerts={() => handleTabChange('alerts')} />
        </div>

        {/* Alerts — direct access, no sub-nav needed */}
        <div id="tabpanel-alerts" role="tabpanel" aria-labelledby="tab-alerts" hidden={activeTab !== 'alerts'}>
          <div className="rounded-lg overflow-hidden" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <div className="flex items-center justify-between px-4 py-3" style={{ borderBottom: '1px solid var(--border)' }}>
              <AlertFilters filters={filters} onChange={setFilters} />
            </div>
            <AlertFeed
              filters={filters}
              subscriptions={selectedSubscriptions}
              onInvestigate={(incidentId, resourceId, resourceName) => {
                const resId = (resourceId ?? '').toLowerCase()
                if (resId.includes('virtualmachinescalesets')) {
                  if (resourceId && resourceName) openVMSSDetail(resourceId, resourceName)
                } else if (resId.includes('managedclusters')) {
                  if (resourceId && resourceName) openAKSDetail(resourceId, resourceName)
                } else {
                  openVMDetail(incidentId, resourceId ?? null, resourceName ?? null)
                }
              }}
            />
          </div>
        </div>

        {/* Resources hub — All Resources · VMs · VMSS · AKS · Disks · AZ Coverage */}
        {activeTab === 'resources' && (
          <div id="tabpanel-resources" role="tabpanel" aria-labelledby="tab-resources">
            <ResourcesHubTab
              subscriptions={selectedSubscriptions}
              onVMClick={(resourceId, resourceName) => openVMDetail(null, resourceId, resourceName)}
              onVMSSClick={openVMSSDetail}
              onAKSClick={openAKSDetail}
            />
          </div>
        )}

        {/* Network hub — Topology · VNet Peerings · Load Balancers · Private Endpoints */}
        {activeTab === 'network' && (
          <div id="tabpanel-network" role="tabpanel" aria-labelledby="tab-network">
            <NetworkHubTab subscriptions={selectedSubscriptions} />
          </div>
        )}

        {/* Security hub — Posture · Compliance · Identity · Certs · Backup · Storage Security */}
        {activeTab === 'security' && (
          <div id="tabpanel-security" role="tabpanel" aria-labelledby="tab-security">
            <SecurityHubTab subscriptions={selectedSubscriptions} />
          </div>
        )}

        {/* Cost hub — FinOps · Budgets · Quota Usage · Capacity · Quota Limits */}
        {activeTab === 'cost' && (
          <div id="tabpanel-cost" role="tabpanel" aria-labelledby="tab-cost">
            <CostHubTab subscriptions={selectedSubscriptions} />
          </div>
        )}

        {/* Change hub — Patch · Deployments · IaC Drift · Maintenance */}
        {activeTab === 'change' && (
          <div id="tabpanel-change" role="tabpanel" aria-labelledby="tab-change">
            <ChangeHubTab subscriptions={selectedSubscriptions} />
          </div>
        )}

        {/* Operations hub — Runbooks · Simulations · Observability · SLA · Quality */}
        {activeTab === 'operations' && (
          <div id="tabpanel-operations" role="tabpanel" aria-labelledby="tab-operations">
            <OperationsHubTab subscriptions={selectedSubscriptions} />
          </div>
        )}

        {/* Audit hub — Audit Log · Agent Traces */}
        {activeTab === 'audit' && (
          <div id="tabpanel-audit" role="tabpanel" aria-labelledby="tab-audit">
            <AuditHubTab
              subscriptions={selectedSubscriptions}
              incidentId={selectedIncidentId ?? undefined}
            />
          </div>
        )}

        {/* Admin hub — Subscriptions · Settings · Tenant */}
        {activeTab === 'admin' && (
          <div id="tabpanel-admin" role="tabpanel" aria-labelledby="tab-admin">
            <AdminHubTab />
          </div>
        )}

      </div>

      {/* ── Detail slide-overs ────────────────────────────────────────────── */}
      {vmDetailOpen && selectedVM && (
        <VMDetailPanel
          incidentId={selectedVM.incidentId}
          resourceId={selectedVM.resourceId}
          resourceName={selectedVM.resourceName}
          onClose={closeVMDetail}
        />
      )}
      {vmssDetailOpen && selectedVMSS && (
        <VMSSDetailPanel
          resourceId={selectedVMSS.resourceId}
          resourceName={selectedVMSS.resourceName}
          onClose={closeVMSSDetail}
        />
      )}
      {aksDetailOpen && selectedAKS && (
        <AKSDetailPanel
          resourceId={selectedAKS.resourceId}
          resourceName={selectedAKS.resourceName}
          onClose={closeAKSDetail}
        />
      )}
    </div>
  )
}
