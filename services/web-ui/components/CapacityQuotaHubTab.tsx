'use client'

import { useState } from 'react'
import { BarChart3, Gauge, BarChart2 } from 'lucide-react'
import QuotaUsageTab from './QuotaUsageTab'
import { CapacityTab } from './CapacityTab'
import { QuotaTab } from './QuotaTab'

export interface CapacityQuotaHubTabProps {
  subscriptions: string[]
  initialSubTab?: string
}

const subTabs = [
  { id: 'quota-usage', label: 'Quota Usage',  icon: BarChart3 },
  { id: 'capacity',    label: 'Capacity',      icon: Gauge     },
  { id: 'quotas',      label: 'Quota Limits',  icon: BarChart2 },
] as const

type SubTabId = typeof subTabs[number]['id']

export function CapacityQuotaHubTab({ subscriptions, initialSubTab }: CapacityQuotaHubTabProps) {
  const [activeSubTab, setActiveSubTab] = useState<SubTabId>(
    (initialSubTab as SubTabId) ?? subTabs[0].id
  )

  return (
    <div className="flex flex-col h-full">
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

      <div className="flex-1 min-h-0">
        {activeSubTab === 'quota-usage' && <QuotaUsageTab />}
        {activeSubTab === 'capacity'    && <CapacityTab subscriptionId={subscriptions[0]} />}
        {activeSubTab === 'quotas'      && <QuotaTab subscriptionId={subscriptions[0]} />}
      </div>
    </div>
  )
}
