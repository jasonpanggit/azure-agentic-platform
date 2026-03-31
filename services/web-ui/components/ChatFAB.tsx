'use client'

import { MessageSquare, X } from 'lucide-react'
import { useAppState } from '@/lib/app-state-context'

export function ChatFAB() {
  const { drawerOpen, setDrawerOpen, isStreaming } = useAppState()

  if (drawerOpen) return null

  return (
    <button
      onClick={() => setDrawerOpen(!drawerOpen)}
      className="fixed bottom-6 right-6 z-50 w-14 h-14 rounded-full flex items-center justify-center text-white transition-transform hover:scale-105 active:scale-95"
      style={{
        background: 'var(--accent-blue)',
        boxShadow: isStreaming
          ? '0 0 0 4px color-mix(in srgb, var(--accent-blue) 30%, transparent), 0 4px 12px rgba(0,0,0,0.3)'
          : '0 4px 12px rgba(0,0,0,0.3)',
        animation: isStreaming ? 'pulse 2s cubic-bezier(0.4,0,0.6,1) infinite' : 'none',
      }}
      aria-label={drawerOpen ? 'Close AI chat' : 'Open AI chat'}
    >
      {drawerOpen ? <X className="h-6 w-6" /> : <MessageSquare className="h-6 w-6" />}
    </button>
  )
}
