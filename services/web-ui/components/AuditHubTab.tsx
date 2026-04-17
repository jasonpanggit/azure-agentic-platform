'use client'
import { useState } from 'react'
import { ClipboardList, GitCommitHorizontal } from 'lucide-react'
import { AuditLogViewer } from './AuditLogViewer'
import { TracesTab } from './TracesTab'

interface AuditHubTabProps {
  subscriptions: string[]
  incidentId?: string
  initialSubTab?: string
}

const subTabs = [
  { id: 'audit-log', label: 'Audit Log', icon: ClipboardList },
  { id: 'traces', label: 'Agent Traces', icon: GitCommitHorizontal },
]

export function AuditHubTab({ subscriptions, incidentId, initialSubTab }: AuditHubTabProps) {
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

      {activeSubTab === 'audit-log' && <AuditLogViewer incidentId={incidentId} />}
      {activeSubTab === 'traces' && <TracesTab subscriptionId={subscriptions[0]} />}
    </div>
  )
}
