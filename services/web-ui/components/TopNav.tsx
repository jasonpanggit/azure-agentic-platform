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
}

export function TopNav({ activeTab, isRefreshing = false }: TopNavProps) {
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
      style={{ background: 'var(--bg-nav)' }}
    >
      {/* Left: logo + separator + breadcrumb */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2">
          <div
            className="w-6 h-6 rounded flex items-center justify-center text-xs font-bold text-white"
            style={{ background: 'var(--accent-blue)' }}
          >
            A
          </div>
          <span className="text-sm font-semibold text-white">Azure AIOps</span>
        </div>
        <div className="w-px h-5" style={{ background: 'var(--border-nav)' }} />
        <span className="text-sm" style={{ color: 'var(--text-muted)' }}>
          {activeTab}
        </span>
      </div>

      {/* Center: subscription selector */}
      <NavSubscriptionPill />

      {/* Right: controls */}
      <div className="flex items-center gap-1">
        <button
          className="w-8 h-8 flex items-center justify-center rounded transition-colors"
          style={{ color: 'var(--text-muted)' }}
          onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--text-nav)' }}
          onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-muted)' }}
          aria-label="Refresh status"
        >
          <RefreshCw className={`h-4 w-4 ${isRefreshing ? 'animate-spin' : ''}`} />
        </button>

        <button
          onClick={toggleTheme}
          className="w-8 h-8 flex items-center justify-center rounded transition-colors"
          style={{ color: 'var(--text-muted)' }}
          onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--text-nav)' }}
          onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-muted)' }}
          aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
        >
          {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </button>

        <button
          className="w-8 h-8 flex items-center justify-center rounded relative"
          style={{ color: 'var(--text-muted)' }}
          aria-label={`${alertCount} alerts`}
        >
          <Bell className="h-4 w-4" />
          {alertCount > 0 && (
            <span
              className="absolute top-1 right-1 min-w-[14px] h-3.5 rounded-full text-[9px] font-bold text-white flex items-center justify-center px-0.5"
              style={{ background: 'var(--accent-red)', lineHeight: 1 }}
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
