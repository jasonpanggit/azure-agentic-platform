'use client'
import { useState } from 'react'
import { Globe, Settings, Building2 } from 'lucide-react'
import { SubscriptionManagementTab } from './SubscriptionManagementTab'
import { SettingsTab } from './SettingsTab'
import { TenantAdminTab } from './TenantAdminTab'

interface AdminHubTabProps {
  initialSubTab?: string
}

const subTabs = [
  { id: 'subscriptions', label: 'Subscriptions', icon: Globe },
  { id: 'settings', label: 'Settings', icon: Settings },
  { id: 'tenant', label: 'Tenant & Admin', icon: Building2 },
]

export function AdminHubTab({ initialSubTab }: AdminHubTabProps) {
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

      {activeSubTab === 'subscriptions' && <SubscriptionManagementTab />}
      {activeSubTab === 'settings' && <SettingsTab />}
      {activeSubTab === 'tenant' && <TenantAdminTab />}
    </div>
  )
}
