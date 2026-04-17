'use client'

import { useState } from 'react'
import { Network, GitMerge, Activity, Lock } from 'lucide-react'
import { TopologyTab } from './TopologyTab'
import VNetPeeringTab from './VNetPeeringTab'
import { LBHealthTab } from './LBHealthTab'
import { PrivateEndpointTab } from './PrivateEndpointTab'

interface NetworkHubTabProps {
  subscriptions: string[]
  initialSubTab?: string
}

const subTabs = [
  { id: 'topology',          label: 'Topology',          icon: Network  },
  { id: 'vnet-peerings',     label: 'VNet Peerings',     icon: GitMerge },
  { id: 'load-balancers',    label: 'Load Balancers',    icon: Activity },
  { id: 'private-endpoints', label: 'Private Endpoints', icon: Lock     },
]

export function NetworkHubTab({
  subscriptions,
  initialSubTab = 'topology',
}: NetworkHubTabProps) {
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

      {activeSubTab === 'topology' && (
        <TopologyTab subscriptions={subscriptions} />
      )}
      {activeSubTab === 'vnet-peerings' && <VNetPeeringTab />}
      {activeSubTab === 'load-balancers' && <LBHealthTab />}
      {activeSubTab === 'private-endpoints' && (
        <PrivateEndpointTab subscriptions={subscriptions} />
      )}
    </div>
  )
}
