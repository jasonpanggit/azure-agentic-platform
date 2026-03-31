export function ThinkingIndicator() {
  return (
    <div className="flex items-start gap-2 mb-3 max-w-[90%]">
      <div
        className="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-semibold flex-shrink-0 mt-0.5"
        style={{ background: 'color-mix(in srgb, var(--accent-blue) 20%, transparent)', color: 'var(--accent-blue)' }}
      >
        AI
      </div>
      <div
        className="rounded-2xl rounded-tl-sm px-3 py-3 flex items-center gap-1.5"
        style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)' }}
      >
        {[0, 0.2, 0.4].map((delay, i) => (
          <span
            key={i}
            className="w-1.5 h-1.5 rounded-full animate-pulse-dot"
            style={{ background: 'var(--accent-blue)', animationDelay: `${delay}s` }}
          />
        ))}
      </div>
    </div>
  )
}
