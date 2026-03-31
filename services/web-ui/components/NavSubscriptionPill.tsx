'use client'

import { Cloud, ChevronDown } from 'lucide-react'
import { SubscriptionSelector } from './SubscriptionSelector'
import { useAppState } from '@/lib/app-state-context'

export function NavSubscriptionPill() {
  const { selectedSubscriptions, setSelectedSubscriptions } = useAppState()
  const count = selectedSubscriptions.length

  return (
    <SubscriptionSelector
      selected={selectedSubscriptions}
      onChange={setSelectedSubscriptions}
      onLoad={setSelectedSubscriptions}
      trigger={
        <button
          className="flex items-center gap-2 rounded-md px-3 h-8 text-sm text-white/90 hover:opacity-85 transition-opacity"
          style={{ background: 'var(--bg-nav-pill)', border: '1px solid var(--border-nav)' }}
        >
          <Cloud className="h-4 w-4 text-white/60" />
          <span>{count === 0 ? 'All subscriptions' : `${count} subscription${count !== 1 ? 's' : ''}`}</span>
          <ChevronDown className="h-3.5 w-3.5 text-white/60" />
        </button>
      }
    />
  )
}
