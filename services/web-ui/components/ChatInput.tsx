'use client'

import { useRef, useEffect } from 'react'
import { SendHorizonal } from 'lucide-react'

interface ChatInputProps {
  value: string
  onChange: (value: string) => void
  onSubmit: () => void
  disabled?: boolean
  placeholder?: string
}

export function ChatInput({
  value, onChange, onSubmit, disabled = false,
  placeholder = 'Ask about any Azure resource...',
}: ChatInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`
  }, [value])

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (!disabled && value.trim()) onSubmit()
    }
  }

  return (
    <div
      className="flex items-end gap-2 px-3 py-3"
      style={{ background: 'var(--bg-surface-raised)', borderTop: '1px solid var(--border)' }}
    >
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        placeholder={placeholder}
        rows={1}
        className="flex-1 resize-none text-sm rounded-lg px-3 py-2 outline-none transition-colors min-h-[36px] max-h-[120px]"
        style={{
          background: 'var(--bg-subtle)',
          border: '1px solid var(--border)',
          color: 'var(--text-primary)',
          fontFamily: 'var(--font-sans)',
        }}
      />
      <button
        onClick={() => { if (!disabled && value.trim()) onSubmit() }}
        disabled={disabled || !value.trim()}
        className="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 transition-colors"
        style={{
          background: disabled || !value.trim() ? 'var(--bg-subtle)' : 'var(--accent-blue)',
          color: disabled || !value.trim() ? 'var(--text-muted)' : '#FFFFFF',
          border: '1px solid var(--border)',
        }}
        aria-label="Send message"
      >
        <SendHorizonal className="h-3.5 w-3.5" />
      </button>
    </div>
  )
}
