'use client'

import { MessageSquare } from 'lucide-react'
import { useAppState } from '@/lib/app-state-context'

export function ChatFAB() {
  const { drawerOpen, setDrawerOpen, isStreaming } = useAppState()

  // Hide FAB when drawer is open — the drawer's own X button handles close,
  // and the FAB overlaps the ChatInput send button at bottom-right.
  if (drawerOpen) return null

  return (
    <button
      onClick={() => setDrawerOpen(true)}
      className="fixed bottom-6 left-6 z-50 w-14 h-14 rounded-full flex items-center justify-center text-white transition-all hover:scale-105 active:scale-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/50 focus-visible:ring-offset-2 cursor-pointer"
      style={{
        background: 'var(--accent-blue)',
        boxShadow: isStreaming
          ? '0 0 0 4px color-mix(in srgb, var(--accent-blue) 30%, transparent), 0 4px 12px rgba(0,0,0,0.3)'
          : '0 4px 12px rgba(0,0,0,0.3)',
        animation: isStreaming ? 'pulse 2s cubic-bezier(0.4,0,0.6,1) infinite' : 'none',
      }}
      aria-label="Open AI chat"
    >
      <MessageSquare className="h-6 w-6" />
    </button>
  )
}
