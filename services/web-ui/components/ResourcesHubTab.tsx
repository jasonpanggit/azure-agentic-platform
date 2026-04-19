'use client'

import { useState } from 'react'
import { Server, Monitor, Layers, Box, HardDrive, Globe, GitBranch, AppWindow, MessageSquare } from 'lucide-react'
import { ResourcesTab } from './ResourcesTab'
import { ResourceHierarchyTab } from './ResourceHierarchyTab'
import { VMTab } from './VMTab'
import { VMSSTab } from './VMSSTab'
import { AKSTab } from './AKSTab'
import DiskAuditTab from './DiskAuditTab'
import { AZCoverageTab } from './AZCoverageTab'
import { AppServiceHealthTab } from './AppServiceHealthTab'
import { QueueDepthTab } from './QueueDepthTab'

interface ResourcesHubTabProps {
  subscriptions: string[]
  onVMClick: (resourceId: string, resourceName: string) => void
  onVMSSClick: (resourceId: string, resourceName: string) => void
  onAKSClick: (resourceId: string, resourceName: string) => void
  initialSubTab?: string
}

const subTabs = [
  { id: 'all-resources',      label: 'All Resources',      icon: Server        },
  { id: 'vms',                label: 'Virtual Machines',   icon: Monitor       },
  { id: 'vmss',               label: 'Scale Sets',         icon: Layers        },
  { id: 'aks',                label: 'Kubernetes',         icon: Box           },
  { id: 'app-services',       label: 'App Services',       icon: AppWindow     },
  { id: 'disks',              label: 'Disks',              icon: HardDrive     },
  { id: 'az-coverage',        label: 'AZ Coverage',        icon: Globe         },
  { id: 'messaging',          label: 'Messaging',          icon: MessageSquare },
  { id: 'resource-hierarchy', label: 'Resource Hierarchy', icon: GitBranch     },
]

export function ResourcesHubTab({
  subscriptions,
  onVMClick,
  onVMSSClick,
  onAKSClick,
  initialSubTab = 'all-resources',
}: ResourcesHubTabProps) {
  const [activeSubTab, setActiveSubTab] = useState(initialSubTab)

  return (
    <div>
      <div
        className="flex gap-1 mb-6 p-1 rounded-lg"
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

      {activeSubTab === 'all-resources' && (
        <ResourcesTab subscriptions={subscriptions} />
      )}
      {activeSubTab === 'vms' && (
        <VMTab subscriptions={subscriptions} onVMClick={onVMClick} />
      )}
      {activeSubTab === 'vmss' && (
        <VMSSTab subscriptions={subscriptions} onVMSSClick={onVMSSClick} />
      )}
      {activeSubTab === 'aks' && (
        <AKSTab subscriptions={subscriptions} onAKSClick={onAKSClick} />
      )}
      {activeSubTab === 'disks' && <DiskAuditTab />}
      {activeSubTab === 'az-coverage'        && <AZCoverageTab />}
      {activeSubTab === 'resource-hierarchy' && <ResourceHierarchyTab subscriptions={subscriptions} />}
      {activeSubTab === 'app-services'       && <AppServiceHealthTab subscriptions={subscriptions} />}
      {activeSubTab === 'messaging'          && <QueueDepthTab subscriptions={subscriptions} />}
    </div>
  )
}
