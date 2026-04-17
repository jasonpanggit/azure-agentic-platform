'use client'
import { useState } from 'react'
import { BookOpen, FlaskConical, Activity, BarChart2, TrendingUp } from 'lucide-react'
import { RunbookTab } from './RunbookTab'
import { SimulationTab } from './SimulationTab'
import { ObservabilityTab } from './ObservabilityTab'
import { SLATab } from './SLATab'
import { QualityFlywheelTab } from './QualityFlywheelTab'

interface OperationsHubTabProps {
  subscriptions: string[]
  initialSubTab?: string
}

const subTabs = [
  { id: 'runbooks', label: 'Runbooks', icon: BookOpen },
  { id: 'simulations', label: 'Simulations', icon: FlaskConical },
  { id: 'observability', label: 'Observability', icon: Activity },
  { id: 'sla', label: 'SLA', icon: BarChart2 },
  { id: 'quality', label: 'Quality', icon: TrendingUp },
]

export function OperationsHubTab({ subscriptions, initialSubTab }: OperationsHubTabProps) {
  const [activeSubTab, setActiveSubTab] = useState(initialSubTab ?? subTabs[0].id)

  return (
    <div>
      <div
        className="flex gap-1 mb-6 p-1 rounded-lg flex-wrap"
        style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
      >
        {subTabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveSubTab(tab.id)}
            className="flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-all"
            style={
              activeSubTab === tab.id
                ? { background: 'var(--accent-blue)', color: '#ffffff' }
                : { color: 'var(--text-secondary)' }
            }
          >
            <tab.icon size={14} aria-label="" />
            {tab.label}
          </button>
        ))}
      </div>

      {activeSubTab === 'runbooks' && <RunbookTab />}
      {activeSubTab === 'simulations' && <SimulationTab subscriptionId={subscriptions[0]} />}
      {activeSubTab === 'observability' && <ObservabilityTab subscriptions={subscriptions} />}
      {activeSubTab === 'sla' && <SLATab subscriptions={subscriptions} />}
      {activeSubTab === 'quality' && <QualityFlywheelTab />}
    </div>
  )
}
