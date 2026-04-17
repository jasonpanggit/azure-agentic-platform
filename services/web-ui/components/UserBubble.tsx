interface UserBubbleProps {
  content: string
  timestamp?: string
}

export function UserBubble({ content, timestamp }: UserBubbleProps) {
  return (
    <div className="group flex flex-col items-end mb-3 ml-auto max-w-[85%] min-w-0 w-full">
      <div
        className="rounded-2xl rounded-br-sm px-3 py-2.5 text-sm text-white break-words overflow-wrap-anywhere"
        style={{ background: 'var(--accent-blue)', overflowWrap: 'anywhere', wordBreak: 'break-word' }}
      >
        {content}
      </div>
      {timestamp && (
        <span className="text-[11px] mt-1 opacity-0 group-hover:opacity-100 transition-opacity" style={{ color: 'var(--text-muted)' }}>
          {timestamp}
        </span>
      )}
    </div>
  )
}
