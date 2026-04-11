'use client'

import { useState, useEffect } from 'react'
import { Bell, ClipboardList, Network, Server, Activity, ShieldCheck, Monitor, TrendingDown } from 'lucide-react'
import { AlertFeed } from './AlertFeed'
import { AlertFilters } from './AlertFilters'
import { AuditLogViewer } from './AuditLogViewer'
import { TopologyTab } from './TopologyTab'
import { ResourcesTab } from './ResourcesTab'
import { ObservabilityTab } from './ObservabilityTab'
import { PatchTab } from './PatchTab'
import { VMTab } from './VMTab'
import { VMDetailPanel } from './VMDetailPanel'
import { CostTab } from './CostTab'
import { useAppState } from '@/lib/app-state-context'

type TabId = 'alerts' | 'audit' | 'topology' | 'resources' | 'vms' | 'cost' | 'observability' | 'patch'

interface FilterState {
  severity?: string
  domain?: string
  status?: string
}

const TABS: { id: TabId; label: string; Icon: React.FC<{ className?: string }> }[] = [
  { id: 'alerts', label: 'Alerts', Icon: Bell },
  { id: 'audit', label: 'Audit', Icon: ClipboardList },
  { id: 'topology', label: 'Topology', Icon: Network },
  { id: 'resources', label: 'Resources', Icon: Server },
  { id: 'vms', label: 'VMs', Icon: Monitor },
  { id: 'cost', label: 'Cost', Icon: TrendingDown },
  { id: 'observability', label: 'Observability', Icon: Activity },
  { id: 'patch', label: 'Patch', Icon: ShieldCheck },
]

interface DashboardPanelProps {
  onTabChange?: (tab: TabId) => void
  /** Called once on mount with a function that navigates to the Alerts tab */
  onRegisterNavToAlerts?: (fn: () => void) => void
}

export function DashboardPanel({ onTabChange, onRegisterNavToAlerts }: DashboardPanelProps) {
  const [activeTab, setActiveTab] = useState<TabId>('alerts')
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

  function handleTabChange(tab: TabId) {
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
      {/* Tab bar */}
      <div
        className="flex items-end flex-shrink-0 pl-4"
        role="tablist"
        aria-label="Dashboard sections"
        style={{ background: 'var(--bg-surface)', borderBottom: '1px solid var(--border)' }}
      >
        {TABS.map(({ id, label, Icon }, index) => {
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
              className="flex items-center gap-1.5 px-4 py-3 text-[13px] transition-colors outline-none relative focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500/60 cursor-pointer"
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
              <Icon className="h-4 w-4" />
              {label}
            </button>
          )
        })}
      </div>

      {/* Tab panels */}
      <div className="flex-1 overflow-auto p-6">
        <div id="tabpanel-alerts" role="tabpanel" aria-labelledby="tab-alerts" hidden={activeTab !== 'alerts'}>
          <div className="rounded-lg overflow-hidden" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <div className="flex items-center justify-between px-4 py-3" style={{ borderBottom: '1px solid var(--border)' }}>
              <AlertFilters filters={filters} onChange={setFilters} />
            </div>
            <AlertFeed filters={filters} subscriptions={selectedSubscriptions} onInvestigate={(incidentId, resourceId, resourceName) => openVMDetail(incidentId, resourceId ?? null, resourceName ?? null)} />
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
    </div>
  )
}
