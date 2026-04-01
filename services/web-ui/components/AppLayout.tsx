'use client'

import { useRef, useState } from 'react'
import { TopNav } from './TopNav'
import { DashboardPanel } from './DashboardPanel'
import { ChatDrawer } from './ChatDrawer'
import { ChatFAB } from './ChatFAB'

export function AppLayout() {
  const [activeTab, setActiveTab] = useState('Alerts')
  const [isRefreshing, setIsRefreshing] = useState(false)
  const navToAlertsRef = useRef<(() => void) | null>(null)

  function handleRefresh() {
    setIsRefreshing(true)
    // Brief visual feedback; actual data refetches are driven by each tab's own polling
    setTimeout(() => setIsRefreshing(false), 800)
  }

  function handleAlertsClick() {
    navToAlertsRef.current?.()
  }

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      {/* Skip-to-content link for keyboard users */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:z-[100] focus:top-2 focus:left-2 focus:px-3 focus:py-1.5 focus:text-sm focus:font-medium focus:rounded focus:text-white focus:outline-none"
        style={{ background: 'var(--accent-blue)' }}
      >
        Skip to main content
      </a>

      <TopNav
        activeTab={activeTab}
        isRefreshing={isRefreshing}
        onRefresh={handleRefresh}
        onAlertsClick={handleAlertsClick}
      />
      <main id="main-content" className="flex-1 overflow-hidden">
        <DashboardPanel
          onTabChange={(tab) => setActiveTab(tab.charAt(0).toUpperCase() + tab.slice(1))}
          onRegisterNavToAlerts={(fn) => { navToAlertsRef.current = fn }}
        />
      </main>
      <ChatDrawer />
      <ChatFAB />
    </div>
  )
}
