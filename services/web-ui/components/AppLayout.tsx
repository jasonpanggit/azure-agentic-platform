'use client'

import { useState } from 'react'
import { TopNav } from './TopNav'
import { DashboardPanel } from './DashboardPanel'
import { ChatDrawer } from './ChatDrawer'
import { ChatFAB } from './ChatFAB'

export function AppLayout() {
  const [activeTab, setActiveTab] = useState('Alerts')

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <TopNav activeTab={activeTab} />
      <div className="flex-1 overflow-hidden">
        <DashboardPanel
          onTabChange={(tab) => setActiveTab(tab.charAt(0).toUpperCase() + tab.slice(1))}
        />
      </div>
      <ChatDrawer />
      <ChatFAB />
    </div>
  )
}
