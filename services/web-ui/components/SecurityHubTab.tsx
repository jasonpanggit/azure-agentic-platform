'use client'

import { useState } from 'react'
import { ShieldCheck, FileCheck, Key, BadgeCheck, DatabaseBackup, HardDrive, FileText, BellRing, Puzzle, Bug } from 'lucide-react'
import { SecurityPostureTab } from './SecurityPostureTab'
import { ComplianceTab } from './ComplianceTab'
import { IdentityRiskTab } from './IdentityRiskTab'
import { CertExpiryTab } from './CertExpiryTab'
import { BackupComplianceTab } from './BackupComplianceTab'
import { StorageSecurityTab } from './StorageSecurityTab'
import { PolicyComplianceTab } from './PolicyComplianceTab'
import { AlertCoverageTab } from './AlertCoverageTab'
import { VMExtensionAuditTab } from './VMExtensionAuditTab'
import { CVEFleetTab } from './CVEFleetTab'

export interface SecurityHubTabProps {
  subscriptions: string[]
  initialSubTab?: string
}

const subTabs = [
  { id: 'posture',          label: 'Security Score',    icon: ShieldCheck    },
  { id: 'compliance',       label: 'Compliance',        icon: FileCheck      },
  { id: 'identity',         label: 'Identity Risk',     icon: Key            },
  { id: 'certs',            label: 'Certificates',      icon: BadgeCheck     },
  { id: 'backup',           label: 'Backup',            icon: DatabaseBackup },
  { id: 'storage',          label: 'Storage Security',  icon: HardDrive      },
  { id: 'policy',           label: 'Policy',            icon: FileText       },
  { id: 'alert-coverage',   label: 'Alert Coverage',    icon: BellRing       },
  { id: 'vm-extensions',    label: 'VM Extensions',     icon: Puzzle         },
  { id: 'cve-exposure',     label: 'CVE Exposure',       icon: Bug            },
]

export function SecurityHubTab({ subscriptions, initialSubTab }: SecurityHubTabProps) {
  const [activeSubTab, setActiveSubTab] = useState(
    initialSubTab ?? subTabs[0].id
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
        {activeSubTab === 'backup'          && <BackupComplianceTab subscriptions={subscriptions} />}
        {activeSubTab === 'storage'         && <StorageSecurityTab />}
        {activeSubTab === 'policy'          && <PolicyComplianceTab subscriptions={subscriptions} />}
        {activeSubTab === 'alert-coverage'  && <AlertCoverageTab subscriptionId={subscriptions[0]} />}
        {activeSubTab === 'vm-extensions'   && <VMExtensionAuditTab subscriptionId={subscriptions[0]} />}
        {activeSubTab === 'cve-exposure'     && <CVEFleetTab subscriptions={subscriptions} />}
      </div>
    </div>
  )
}
