'use client'

import { createContext, useContext, useEffect, useRef, useState } from 'react'
import type { Message } from '@/types/sse'

interface ManagedSubscription {
  subscription_id: string
  display_name: string
  credential_type: 'spn' | 'mi'
  environment: string
}

interface AppStateContextValue {
  drawerOpen: boolean
  setDrawerOpen: (open: boolean) => void
  messages: Message[]
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>
  isStreaming: boolean
  setIsStreaming: (v: boolean) => void
  threadId: string | null
  setThreadId: (id: string | null) => void
  runId: string | null
  setRunId: (id: string | null) => void
  runKey: number
  setRunKey: React.Dispatch<React.SetStateAction<number>>
  currentAgentRef: React.MutableRefObject<string>
  input: string
  setInput: (v: string) => void
  alertCount: number
  setAlertCount: (n: number) => void
  selectedIncidentId: string | null
  setSelectedIncidentId: (id: string | null) => void
  selectedSubscriptions: string[]
  setSelectedSubscriptions: (subs: string[]) => void
  managedSubscriptions: ManagedSubscription[]
}

const AppStateContext = createContext<AppStateContextValue | null>(null)

export function AppStateProvider({ children }: { children: React.ReactNode }) {
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [messages, setMessages] = useState<Message[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [threadId, setThreadId] = useState<string | null>(null)
  const [runId, setRunId] = useState<string | null>(null)
  const [runKey, setRunKey] = useState(0)
  const currentAgentRef = useRef('Orchestrator')
  const [input, setInput] = useState('')
  const [alertCount, setAlertCount] = useState(0)
  const [selectedIncidentId, setSelectedIncidentId] = useState<string | null>(null)
  const [selectedSubscriptions, setSelectedSubscriptions] = useState<string[]>([])
  const [managedSubscriptions, setManagedSubscriptions] = useState<ManagedSubscription[]>([])

  useEffect(() => {
    fetch('/api/proxy/subscriptions/managed')
      .then(r => r.json())
      .then(d => setManagedSubscriptions(d.subscriptions ?? []))
      .catch(() => {}) // silent fail — non-critical
  }, [])

  return (
    <AppStateContext.Provider value={{
      drawerOpen, setDrawerOpen,
      messages, setMessages,
      isStreaming, setIsStreaming,
      threadId, setThreadId,
      runId, setRunId,
      runKey, setRunKey,
      currentAgentRef,
      input, setInput,
      alertCount, setAlertCount,
      selectedIncidentId, setSelectedIncidentId,
      selectedSubscriptions, setSelectedSubscriptions,
      managedSubscriptions,
    }}>
      {children}
    </AppStateContext.Provider>
  )
}

export function useAppState() {
  const ctx = useContext(AppStateContext)
  if (!ctx) throw new Error('useAppState must be used within AppStateProvider')
  return ctx
}
