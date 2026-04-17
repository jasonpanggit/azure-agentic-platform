'use client'

import { useState } from 'react'
import { ShieldCheck, FileCheck, Key, BadgeCheck, DatabaseBackup, HardDrive } from 'lucide-react'
import { SecurityPostureTab } from './SecurityPostureTab'
import { ComplianceTab } from './ComplianceTab'
import { IdentityRiskTab } from './IdentityRiskTab'
import { CertExpiryTab } from './CertExpiryTab'
import { BackupComplianceTab } from './BackupComplianceTab'
import { StorageSecurityTab } from './StorageSecurityTab'

export interface SecurityHubTabProps {
  subscriptions: string[]
  initialSubTab?: string
}

const subTabs = [
  { id: 'posture',     label: 'Security Score',    icon: ShieldCheck     },
  { id: 'compliance',  label: 'Compliance',         icon: FileCheck       },
  { id: 'identity',    label: 'Identity Risk',      icon: Key             },
  { id: 'certs',       label: 'Certificates',       icon: BadgeCheck      },
  { id: 'backup',      label: 'Backup',             icon: DatabaseBackup  },
  { id: 'storage',     label: 'Storage Security',   icon: HardDrive       },
] as const

type SubTabId = typeof subTabs[number]['id']

export function SecurityHubTab({ subscriptions, initialSubTab }: SecurityHubTabProps) {
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
        {activeSubTab === 'posture'    && <SecurityPostureTab subscriptionId={subscriptions[0]} />}
        {activeSubTab === 'compliance' && <ComplianceTab subscriptions={subscriptions} />}
        {activeSubTab === 'identity'   && <IdentityRiskTab />}
        {activeSubTab === 'certs'      && <CertExpiryTab />}
        {activeSubTab === 'backup'     && <BackupComplianceTab subscriptions={subscriptions} />}
        {activeSubTab === 'storage'    && <StorageSecurityTab />}
      </div>
    </div>
  )
}
