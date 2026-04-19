'use client'
import { useState } from 'react'
import { ShieldCheck, GitPullRequest, GitBranch, Wrench, Zap } from 'lucide-react'
import { PatchTab } from './PatchTab'
import { DeploymentTab } from './DeploymentTab'
import { DriftTab } from './DriftTab'
import { MaintenanceTab } from './MaintenanceTab'
import { ChangeIntelligenceTab } from './ChangeIntelligenceTab'

interface ChangeHubTabProps {
  subscriptions: string[]
  initialSubTab?: string
}

const subTabs = [
  { id: 'patch',              label: 'Patch Management',    icon: ShieldCheck   },
  { id: 'deployments',        label: 'Deployments',         icon: GitPullRequest },
  { id: 'drift',              label: 'IaC Drift',           icon: GitBranch     },
  { id: 'maintenance',        label: 'Maintenance',         icon: Wrench        },
  { id: 'change-intelligence', label: 'Change Intelligence', icon: Zap          },
]

export function ChangeHubTab({ subscriptions, initialSubTab }: ChangeHubTabProps) {
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

      {activeSubTab === 'patch' && <PatchTab subscriptions={subscriptions} />}
      {activeSubTab === 'deployments' && <DeploymentTab resourceGroup={undefined} />}
      {activeSubTab === 'drift' && <DriftTab subscriptionId={subscriptions[0]} />}
      {activeSubTab === 'maintenance' && <MaintenanceTab subscriptions={subscriptions} />}
      {activeSubTab === 'change-intelligence' && <ChangeIntelligenceTab subscriptions={subscriptions} />}
    </div>
  )
}
