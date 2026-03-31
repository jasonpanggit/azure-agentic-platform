'use client'

import { useState } from 'react'
import { Bell, ClipboardList, Network, Server, Activity } from 'lucide-react'
import { AlertFeed } from './AlertFeed'
import { AlertFilters } from './AlertFilters'
import { AuditLogViewer } from './AuditLogViewer'
import { TopologyTab } from './TopologyTab'
import { ResourcesTab } from './ResourcesTab'
import { ObservabilityTab } from './ObservabilityTab'
import { useAppState } from '@/lib/app-state-context'

type TabId = 'alerts' | 'audit' | 'topology' | 'resources' | 'observability'

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
  { id: 'observability', label: 'Observability', Icon: Activity },
]

interface DashboardPanelProps {
  onTabChange?: (tab: TabId) => void
}

export function DashboardPanel({ onTabChange }: DashboardPanelProps) {
  const [activeTab, setActiveTab] = useState<TabId>('alerts')
  const [filters, setFilters] = useState<FilterState>({})
  const { selectedSubscriptions, selectedIncidentId } = useAppState()

  function handleTabChange(tab: TabId) {
    setActiveTab(tab)
    onTabChange?.(tab)
  }

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
              className="flex items-center gap-1.5 px-4 py-3 text-[13px] transition-colors outline-none relative"
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
            <AlertFeed filters={filters} subscriptions={selectedSubscriptions} />
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

        <div id="tabpanel-observability" role="tabpanel" aria-labelledby="tab-observability" hidden={activeTab !== 'observability'}>
          <div className="rounded-lg overflow-hidden" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <ObservabilityTab subscriptions={selectedSubscriptions} />
          </div>
        </div>
      </div>
    </div>
  )
}
