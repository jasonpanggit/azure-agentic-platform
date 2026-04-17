'use client'

import { useState, useEffect } from 'react'
import { Bell, ClipboardList, Network, Server, Activity, ShieldCheck, Monitor, TrendingDown, Scaling, Container, BookOpen, LayoutDashboard, Settings, DollarSign, FileCheck, BarChart2, Gauge, GitBranch, GitPullRequest, TrendingUp, Building2, BarChart3, Globe, MessageSquare, HardDrive } from 'lucide-react'
import { AlertFeed } from './AlertFeed'
import { AlertFilters } from './AlertFilters'
import { AuditLogViewer } from './AuditLogViewer'
import { TopologyTab } from './TopologyTab'
import { ResourcesTab } from './ResourcesTab'
import { ObservabilityTab } from './ObservabilityTab'
import { PatchTab } from './PatchTab'
import { VMTab } from './VMTab'
import { VMDetailPanel } from './VMDetailPanel'
import { VMSSTab } from './VMSSTab'
import { VMSSDetailPanel } from './VMSSDetailPanel'
import { AKSTab } from './AKSTab'
import { AKSDetailPanel } from './AKSDetailPanel'
import { CostTab } from './CostTab'
import { RunbookTab } from './RunbookTab'
import { ComplianceTab } from './ComplianceTab'
import { OpsTab } from './OpsTab'
import { SettingsTab } from './SettingsTab'
import { SLATab } from './SLATab'
import { CapacityTab } from './CapacityTab'
import { SecurityPostureTab } from './SecurityPostureTab'
import { DriftTab } from './DriftTab'
import { DeploymentTab } from './DeploymentTab'
import { QualityFlywheelTab } from './QualityFlywheelTab'
import { TenantAdminTab } from './TenantAdminTab'
import { QuotaTab } from './QuotaTab'
import { AppServiceHealthTab } from './AppServiceHealthTab'
import { QueueDepthTab } from './QueueDepthTab'
import { VMExtensionAuditTab } from './VMExtensionAuditTab'
import { AlertCoverageTab } from './AlertCoverageTab'
import { useAppState } from '@/lib/app-state-context'

type TabId = 'ops' | 'alerts' | 'audit' | 'topology' | 'resources' | 'vms' | 'vmss' | 'aks' | 'cost' | 'observability' | 'patch' | 'compliance' | 'runbooks' | 'sla' | 'capacity' | 'quotas' | 'security-posture' | 'drift' | 'deployments' | 'quality' | 'app-services' | 'queue-depth' | 'vm-extensions' | 'alert-coverage' | 'settings' | 'admin'

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

/**
 * Tab groups keep the nav readable as more tabs are added.
 * Each group is separated by a thin vertical divider.
 * To add a new tab: append to the appropriate group (or create a new one)
 * and add its TabId to the TabId union above.
 */
const TAB_GROUPS: TabDef[][] = [
  // Core operations
  [
    { id: 'ops',         label: 'Ops',         Icon: LayoutDashboard },
    { id: 'alerts',      label: 'Alerts',      Icon: Bell },
    { id: 'audit',       label: 'Audit',       Icon: ClipboardList },
    { id: 'topology',    label: 'Topology',    Icon: Network },
  ],
  // Resources
  [
    { id: 'resources',   label: 'Resources',   Icon: Server },
    { id: 'vms',         label: 'VMs',         Icon: Monitor },
    { id: 'vmss',        label: 'VMSS',        Icon: Scaling },
    { id: 'aks',         label: 'AKS',         Icon: Container },
    { id: 'app-services', label: 'App Services', Icon: Globe },
    { id: 'queue-depth',  label: 'Queues',       Icon: MessageSquare },
  ],
  // Monitoring & cost
  [
    { id: 'cost',          label: 'FinOps',        Icon: DollarSign },
    { id: 'observability', label: 'Observability', Icon: Activity },
    { id: 'sla',           label: 'SLA',           Icon: BarChart2 },
    { id: 'capacity',      label: 'Capacity',      Icon: Gauge },
    { id: 'quotas',        label: 'Quotas',        Icon: BarChart3 },
  ],
  // Security & compliance
  [
    { id: 'patch',            label: 'Patch',           Icon: ShieldCheck },
    { id: 'compliance',       label: 'Compliance',      Icon: FileCheck },
    { id: 'security-posture', label: 'Security Score',  Icon: ShieldCheck },
    { id: 'runbooks',         label: 'Runbooks',        Icon: BookOpen },
    { id: 'drift',            label: 'IaC Drift',       Icon: GitBranch },
    { id: 'deployments',      label: 'Deployments',     Icon: GitPullRequest },
    { id: 'quality',          label: 'Quality',         Icon: TrendingUp },
    { id: 'vm-extensions',    label: 'VM Extensions',   Icon: HardDrive },
    { id: 'alert-coverage',   label: 'Alert Coverage',  Icon: Bell },
  ],
  // Config
  [
    { id: 'settings',    label: 'Settings',    Icon: Settings },
    { id: 'admin',       label: 'Admin',       Icon: Building2 },
  ],
]

// Flat list used for keyboard navigation (arrow keys cycle through all tabs in order)
const TABS: TabDef[] = TAB_GROUPS.flat()

interface DashboardPanelProps {
  onTabChange?: (tab: TabId) => void
  /** Called once on mount with a function that navigates to the Alerts tab */
  onRegisterNavToAlerts?: (fn: () => void) => void
}

export function DashboardPanel({ onTabChange, onRegisterNavToAlerts }: DashboardPanelProps) {
  const [activeTab, setActiveTab] = useState<TabId>('ops')
  const [filters, setFilters] = useState<FilterState>({})
  const [vmDetailOpen, setVMDetailOpen] = useState(false)
  const [selectedVM, setSelectedVM] = useState<{
    incidentId: string | null
    resourceId: string | null
    resourceName: string | null
  } | null>(null)
  const { selectedSubscriptions, selectedIncidentId } = useAppState()

  function openVMDetail(incidentId: string | null, resourceId: string | null, resourceName: string | null) {
    setSelectedVM({ incidentId, resourceId, resourceName })
    setVMDetailOpen(true)
  }

  function closeVMDetail() {
    setVMDetailOpen(false)
    setSelectedVM(null)
  }

  const [vmssDetailOpen, setVMSSDetailOpen] = useState(false)
  const [selectedVMSS, setSelectedVMSS] = useState<{ resourceId: string; resourceName: string } | null>(null)

  function openVMSSDetail(resourceId: string, resourceName: string) {
    setSelectedVMSS({ resourceId, resourceName })
    setVMSSDetailOpen(true)
  }

  function closeVMSSDetail() {
    setVMSSDetailOpen(false)
    setSelectedVMSS(null)
  }

  const [aksDetailOpen, setAKSDetailOpen] = useState(false)
  const [selectedAKS, setSelectedAKS] = useState<{ resourceId: string; resourceName: string } | null>(null)

  function openAKSDetail(resourceId: string, resourceName: string) {
    setSelectedAKS({ resourceId, resourceName })
    setAKSDetailOpen(true)
  }

  function closeAKSDetail() {
    setAKSDetailOpen(false)
    setSelectedAKS(null)
  }

  function handleTabChange(tab: TabId) {
    // Close any open detail panels when switching tabs to prevent stacked overlays
    setVMDetailOpen(false)
    setSelectedVM(null)
    setVMSSDetailOpen(false)
    setSelectedVMSS(null)
    setAKSDetailOpen(false)
    setSelectedAKS(null)
    setActiveTab(tab)
    onTabChange?.(tab)
  }

  // Register the navigate-to-alerts function with the parent once on mount
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
      {/* Tab bar
            - overflow-x-auto + whitespace-nowrap: scrolls horizontally when tabs exceed viewport width
            - [&::-webkit-scrollbar]:hidden: hides the scrollbar track so the bar looks clean
            - The right-edge fade gradient (::after pseudo via inline style) hints that more tabs exist
            - z-35 keeps tabs clickable above the z-30 detail-panel backdrop
      */}
      <div
        className="flex items-end shrink-0 relative z-[35] overflow-x-auto [&::-webkit-scrollbar]:hidden"
        role="tablist"
        aria-label="Dashboard sections"
        style={{
          background: 'var(--bg-surface)',
          borderBottom: '1px solid var(--border)',
          scrollbarWidth: 'none', // Firefox
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
                  className="flex items-center gap-1.5 px-3 py-3 text-[13px] transition-colors outline-none relative whitespace-nowrap shrink-0 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500/60 cursor-pointer"
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
            {/* Group divider — not rendered after the last group */}
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

      {/* Tab panels */}
      <div className="flex-1 overflow-auto p-6">
        <div id="tabpanel-ops" role="tabpanel" aria-labelledby="tab-ops" hidden={activeTab !== 'ops'}>
          <OpsTab subscriptions={selectedSubscriptions} onNavigateToAlerts={() => handleTabChange('alerts')} />
        </div>

        <div id="tabpanel-alerts" role="tabpanel" aria-labelledby="tab-alerts" hidden={activeTab !== 'alerts'}>
          <div className="rounded-lg overflow-hidden" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <div className="flex items-center justify-between px-4 py-3" style={{ borderBottom: '1px solid var(--border)' }}>
              <AlertFilters filters={filters} onChange={setFilters} />
            </div>
            <AlertFeed filters={filters} subscriptions={selectedSubscriptions} onInvestigate={(incidentId, resourceId, resourceName) => {
              const resId = (resourceId ?? '').toLowerCase()
              if (resId.includes('virtualmachinescalesets')) {
                if (resourceId && resourceName) openVMSSDetail(resourceId, resourceName)
              } else if (resId.includes('managedclusters')) {
                if (resourceId && resourceName) openAKSDetail(resourceId, resourceName)
              } else {
                openVMDetail(incidentId, resourceId ?? null, resourceName ?? null)
              }
            }} />
          </div>
        </div>

        <div id="tabpanel-audit" role="tabpanel" aria-labelledby="tab-audit" hidden={activeTab !== 'audit'}>
          <div className="rounded-lg overflow-hidden" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <AuditLogViewer incidentId={selectedIncidentId ?? undefined} />
          </div>
        </div>

        <div id="tabpanel-topology" role="tabpanel" aria-labelledby="tab-topology" hidden={activeTab !== 'topology'}>
          <div className="rounded-lg overflow-hidden" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <TopologyTab subscriptions={selectedSubscriptions} />
          </div>
        </div>

        <div id="tabpanel-resources" role="tabpanel" aria-labelledby="tab-resources" hidden={activeTab !== 'resources'}>
          <div className="rounded-lg overflow-hidden" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <ResourcesTab subscriptions={selectedSubscriptions} />
          </div>
        </div>

        <div id="tabpanel-vms" role="tabpanel" aria-labelledby="tab-vms" hidden={activeTab !== 'vms'}>
          <div className="rounded-lg overflow-hidden" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <VMTab subscriptions={selectedSubscriptions} onVMClick={(resourceId, resourceName) => openVMDetail(null, resourceId, resourceName)} />
          </div>
        </div>

        <div id="tabpanel-vmss" role="tabpanel" aria-labelledby="tab-vmss" hidden={activeTab !== 'vmss'}>
          <div className="rounded-lg overflow-hidden" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <VMSSTab subscriptions={selectedSubscriptions} onVMSSClick={openVMSSDetail} />
          </div>
        </div>

        <div id="tabpanel-aks" role="tabpanel" aria-labelledby="tab-aks" hidden={activeTab !== 'aks'}>
          <div className="rounded-lg overflow-hidden" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <AKSTab subscriptions={selectedSubscriptions} onAKSClick={openAKSDetail} />
          </div>
        </div>

        <div id="tabpanel-app-services" role="tabpanel" aria-labelledby="tab-app-services" hidden={activeTab !== 'app-services'}>
          <div className="rounded-lg overflow-hidden" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <AppServiceHealthTab subscriptions={selectedSubscriptions} />
          </div>
        </div>

        <div id="tabpanel-queue-depth" role="tabpanel" aria-labelledby="tab-queue-depth" hidden={activeTab !== 'queue-depth'}>
          <div className="rounded-lg overflow-hidden" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <QueueDepthTab subscriptions={selectedSubscriptions} />
          </div>
        </div>
        <div id="tabpanel-cost" role="tabpanel" aria-labelledby="tab-cost" hidden={activeTab !== 'cost'}>
          <div className="rounded-lg overflow-hidden" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <CostTab subscriptions={selectedSubscriptions} />
          </div>
        </div>

        <div id="tabpanel-observability" role="tabpanel" aria-labelledby="tab-observability" hidden={activeTab !== 'observability'}>
          <div className="rounded-lg overflow-hidden" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <ObservabilityTab subscriptions={selectedSubscriptions} />
          </div>
        </div>

        <div id="tabpanel-patch" role="tabpanel" aria-labelledby="tab-patch" hidden={activeTab !== 'patch'}>
          <div className="rounded-lg overflow-hidden" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <PatchTab subscriptions={selectedSubscriptions} />
          </div>
        </div>

        <div id="tabpanel-compliance" role="tabpanel" aria-labelledby="tab-compliance" hidden={activeTab !== 'compliance'}>
          <div className="rounded-lg overflow-hidden" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <ComplianceTab subscriptions={selectedSubscriptions} />
          </div>
        </div>

        <div id="tabpanel-runbooks" role="tabpanel" aria-labelledby="tab-runbooks" hidden={activeTab !== 'runbooks'}>
          <div className="rounded-lg overflow-hidden p-4" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <RunbookTab />
          </div>
        </div>

        <div id="tabpanel-sla" role="tabpanel" aria-labelledby="tab-sla" hidden={activeTab !== 'sla'}>
          <div className="rounded-lg overflow-hidden" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <SLATab subscriptions={selectedSubscriptions} />
          </div>
        </div>

        <div id="tabpanel-capacity" role="tabpanel" aria-labelledby="tab-capacity" hidden={activeTab !== 'capacity'}>
          {activeTab === 'capacity' && <CapacityTab subscriptionId={selectedSubscriptions[0]} />}
        </div>

        <div id="tabpanel-quotas" role="tabpanel" aria-labelledby="tab-quotas" hidden={activeTab !== 'quotas'}>
          {activeTab === 'quotas' && <QuotaTab subscriptionId={selectedSubscriptions[0]} />}
        </div>

        <div id="tabpanel-security-posture" role="tabpanel" aria-labelledby="tab-security-posture" hidden={activeTab !== 'security-posture'}>
          {activeTab === 'security-posture' && <SecurityPostureTab subscriptionId={selectedSubscriptions[0]} />}
        </div>

        <div id="tabpanel-drift" role="tabpanel" aria-labelledby="tab-drift" hidden={activeTab !== 'drift'}>
          {activeTab === 'drift' && <DriftTab subscriptionId={selectedSubscriptions[0]} />}
        </div>

        <div id="tabpanel-deployments" role="tabpanel" aria-labelledby="tab-deployments" hidden={activeTab !== 'deployments'}>
          {activeTab === 'deployments' && <DeploymentTab resourceGroup={undefined} />}
        </div>

        <div id="tabpanel-quality" role="tabpanel" aria-labelledby="tab-quality" hidden={activeTab !== 'quality'}>
          {activeTab === 'quality' && <QualityFlywheelTab />}
        </div>

        <div id="tabpanel-vm-extensions" role="tabpanel" aria-labelledby="tab-vm-extensions" hidden={activeTab !== 'vm-extensions'}>
          {activeTab === 'vm-extensions' && <VMExtensionAuditTab subscriptionId={selectedSubscriptions[0]} />}
        </div>

        <div id="tabpanel-alert-coverage" role="tabpanel" aria-labelledby="tab-alert-coverage" hidden={activeTab !== 'alert-coverage'}>
          {activeTab === 'alert-coverage' && <AlertCoverageTab subscriptionId={selectedSubscriptions[0]} />}
        </div>

        <div id="tabpanel-settings" role="tabpanel" aria-labelledby="tab-settings" hidden={activeTab !== 'settings'}>
          <SettingsTab />
        </div>

        <div id="tabpanel-admin" role="tabpanel" aria-labelledby="tab-admin" hidden={activeTab !== 'admin'}>
          {activeTab === 'admin' && <TenantAdminTab />}
        </div>
      </div>

      {/* VM Detail Panel + backdrop */}
      {vmDetailOpen && selectedVM && (
        <>
          <div
            className="fixed inset-0 z-30"
            style={{ background: 'rgba(0,0,0,0.3)' }}
            onClick={closeVMDetail}
          />
          <VMDetailPanel
            incidentId={selectedVM.incidentId}
            resourceId={selectedVM.resourceId}
            resourceName={selectedVM.resourceName}
            onClose={closeVMDetail}
          />
        </>
      )}

      {/* VMSS Detail Panel + backdrop */}
      {vmssDetailOpen && selectedVMSS && (
        <>
          <div
            className="fixed inset-0 z-30"
            style={{ background: 'rgba(0,0,0,0.3)' }}
            onClick={closeVMSSDetail}
          />
          <VMSSDetailPanel
            resourceId={selectedVMSS.resourceId}
            resourceName={selectedVMSS.resourceName}
            onClose={closeVMSSDetail}
          />
        </>
      )}

      {/* AKS Detail Panel + backdrop */}
      {aksDetailOpen && selectedAKS && (
        <>
          <div
            className="fixed inset-0 z-30"
            style={{ background: 'rgba(0,0,0,0.3)' }}
            onClick={closeAKSDetail}
          />
          <AKSDetailPanel
            resourceId={selectedAKS.resourceId}
            resourceName={selectedAKS.resourceName}
            onClose={closeAKSDetail}
          />
        </>
      )}
    </div>
  )
}
