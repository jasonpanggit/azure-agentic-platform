import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface ChatBubbleProps {
  agentName: string
  content: string
  isStreaming?: boolean
  timestamp?: string
  isError?: boolean
}

export function ChatBubble({ agentName, content, isStreaming, timestamp, isError = false }: ChatBubbleProps) {
  if (isError) {
    return (
      <div className="group flex flex-col mb-3 max-w-[90%] self-start">
        <div
          className="rounded-lg px-3 py-2.5"
          style={{
            background: 'color-mix(in srgb, var(--accent-red) 10%, transparent)',
            borderLeft: '4px solid var(--accent-red)',
            border: '1px solid var(--border)',
            borderLeftWidth: '4px',
          }}
        >
          <div className="text-[11px] font-semibold mb-1 uppercase tracking-wide" style={{ color: 'var(--accent-red)' }}>
            System
          </div>
          <p className="text-sm" style={{ color: 'var(--text-primary)' }}>{content}</p>
        </div>
        {timestamp && (
          <span className="text-[11px] mt-1 opacity-0 group-hover:opacity-100 transition-opacity" style={{ color: 'var(--text-muted)' }}>
            {timestamp}
          </span>
        )}
      </div>
    )
  }

  return (
    <div className="group flex items-start gap-2 mb-3 max-w-[90%] self-start">
      <div
        className="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-semibold flex-shrink-0 mt-0.5"
        style={{ background: 'color-mix(in srgb, var(--accent-blue) 20%, transparent)', color: 'var(--accent-blue)' }}
      >
        AI
      </div>
      <div className="flex flex-col min-w-0">
        <div
          className="rounded-2xl rounded-tl-sm px-3 py-2.5"
          style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)' }}
        >
          <div className="chat-prose">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
            {isStreaming && (
              <span
                className="inline-block w-0.5 h-3.5 ml-0.5 animate-blink-cursor"
                style={{ background: 'var(--text-primary)' }}
              />
            )}
          </div>
        </div>
        {timestamp && (
          <span className="text-[11px] mt-1 opacity-0 group-hover:opacity-100 transition-opacity" style={{ color: 'var(--text-muted)' }}>
            {timestamp}
          </span>
        )}
      </div>
    </div>
  )
}
