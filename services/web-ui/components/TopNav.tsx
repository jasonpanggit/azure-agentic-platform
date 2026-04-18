'use client'

import { Bell, RefreshCw, Sun, Moon, LogOut } from 'lucide-react'
import { useMsal } from '@azure/msal-react'
import { useTheme } from '@/lib/theme-context'
import { useAppState } from '@/lib/app-state-context'
import { NavSubscriptionPill } from './NavSubscriptionPill'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuItem,
} from '@/components/ui/dropdown-menu'

interface TopNavProps {
  activeTab: string
  isRefreshing?: boolean
  onRefresh?: () => void
  onAlertsClick?: () => void
}

export function TopNav({ activeTab, isRefreshing = false, onRefresh, onAlertsClick }: TopNavProps) {
  const { theme, toggleTheme } = useTheme()
  const { alertCount } = useAppState()
  const { accounts, instance } = useMsal()

  const account = accounts[0]
  const initials = account?.name
    ? account.name.split(' ').map((n: string) => n[0]).slice(0, 2).join('').toUpperCase()
    : 'U'

  return (
    <nav
      className="flex items-center justify-between px-4 h-12 w-full sticky top-0 z-50 flex-shrink-0"
      style={{
        background: 'linear-gradient(to bottom, #0D1117, #111827)',
        borderBottom: '1px solid rgba(56,139,253,0.2)',
      }}
      aria-label="Main navigation"
    >
      {/* Left: logo + separator + breadcrumb */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2">
          <div
            className="w-6 h-6 rounded flex items-center justify-center text-xs font-bold text-white"
            style={{ background: 'var(--accent-blue)', boxShadow: '0 0 0 1px rgba(56,139,253,0.3)' }}
            aria-hidden="true"
          >
            A
          </div>
          <span className="text-sm font-medium text-white">Azure Agentic Platform</span>
        </div>
        <span className="text-sm" style={{ color: 'var(--border-nav)' }} aria-hidden="true">/</span>
        <span className="text-sm" style={{ color: 'var(--text-muted)' }} aria-current="page">
          {activeTab}
        </span>
      </div>

      {/* Center: subscription selector */}
      <NavSubscriptionPill />

      {/* Right: controls */}
      <div className="flex items-center gap-1">
        <button
          onClick={onRefresh}
          disabled={isRefreshing || !onRefresh}
          className="w-8 h-8 flex items-center justify-center rounded-md transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/50 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
          style={{ color: 'var(--text-muted)' }}
          onMouseEnter={(e) => { if (!isRefreshing) e.currentTarget.style.color = 'var(--text-nav)' }}
          onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-muted)' }}
          aria-label={isRefreshing ? 'Refreshing data…' : 'Refresh data'}
        >
          <RefreshCw className={`h-4 w-4 ${isRefreshing ? 'animate-spin' : ''}`} />
        </button>

        <button
          onClick={toggleTheme}
          className="w-8 h-8 flex items-center justify-center rounded-md transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/50 cursor-pointer"
          style={{ color: 'var(--text-muted)' }}
          onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--text-nav)' }}
          onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-muted)' }}
          aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
        >
          {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </button>

        <button
          onClick={onAlertsClick}
          className="w-8 h-8 flex items-center justify-center rounded-md relative transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/50 cursor-pointer"
          style={{ color: 'var(--text-muted)' }}
          onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--text-nav)' }}
          onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-muted)' }}
          aria-label={alertCount > 0 ? `View ${alertCount} alert${alertCount !== 1 ? 's' : ''}` : 'No active alerts'}
        >
          <Bell className="h-4 w-4" />
          {alertCount > 0 && (
            <span
              className="absolute top-1 right-1 min-w-[14px] h-3.5 rounded-full text-[9px] font-bold text-white flex items-center justify-center px-0.5"
              style={{ background: 'var(--accent-red)', lineHeight: 1 }}
              aria-hidden="true"
            >
              {alertCount > 99 ? '99+' : alertCount}
            </span>
          )}
        </button>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-semibold text-white ml-1"
              style={{ background: 'var(--accent-blue)' }}
              aria-label="User menu"
            >
              {initials}
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-52">
            <DropdownMenuLabel>
              <div className="font-semibold text-sm">{account?.name ?? 'User'}</div>
              <div className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
                {account?.username ?? ''}
              </div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onClick={() => instance.logoutRedirect()}
              className="cursor-pointer"
              style={{ color: 'var(--accent-red)' }}
            >
              <LogOut className="h-4 w-4 mr-2" />
              Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </nav>
  )
}
