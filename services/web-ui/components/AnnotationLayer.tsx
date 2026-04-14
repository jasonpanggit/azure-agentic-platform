'use client';

import React, { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { Pin, Send } from 'lucide-react';
import { cn } from '@/lib/utils';

export interface Annotation {
  id: string;
  operator_id: string;
  display_name: string;
  content: string;
  trace_event_id: string | null;
  created_at: string;
}

interface AnnotationLayerProps {
  incidentId: string;
  annotations: Annotation[];
  /** If provided, new annotations will be pinned to this trace event */
  traceEventId?: string | null;
  onAnnotationAdded?: (annotation: Annotation) => void;
  className?: string;
}

/**
 * AnnotationLayer — annotation list + input for war room investigation notes.
 *
 * Calls POST /api/proxy/war-room/annotations to persist new annotations.
 * Renders existing annotations in chronological order.
 * Dark-mode safe — CSS semantic tokens only.
 */
export function AnnotationLayer({
  incidentId,
  annotations,
  traceEventId = null,
  onAnnotationAdded,
  className,
}: AnnotationLayerProps) {
  const [draft, setDraft] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit() {
    const content = draft.trim();
    if (!content || submitting) return;

    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/proxy/war-room/annotations?incident_id=${encodeURIComponent(incidentId)}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content, trace_event_id: traceEventId ?? null }),
        }
      );
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.error ?? `Error ${res.status}`);
      }
      const data = await res.json();
      setDraft('');
      onAnnotationAdded?.(data.annotation as Annotation);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save annotation');
    } finally {
      setSubmitting(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      handleSubmit();
    }
  }

  return (
    <div className={cn('flex flex-col gap-3', className)}>
      {/* Annotation list */}
      <div className="flex flex-col gap-2 max-h-64 overflow-y-auto">
        {annotations.length === 0 ? (
          <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
            No annotations yet. Pin a note to start the investigation record.
          </p>
        ) : (
          annotations.map((a) => (
            <div
              key={a.id}
              className="rounded-md px-3 py-2 text-sm"
              style={{
                background: 'color-mix(in srgb, var(--accent-blue) 8%, var(--bg-canvas))',
                borderLeft: '3px solid var(--accent-blue)',
              }}
            >
              <div className="flex items-center gap-2 mb-1">
                <span className="font-semibold text-xs" style={{ color: 'var(--text-primary)' }}>
                  {a.display_name || a.operator_id}
                </span>
                {a.trace_event_id && (
                  <Badge
                    variant="outline"
                    className="text-[10px] px-1 py-0 flex items-center gap-1"
                    style={{ color: 'var(--accent-blue)', borderColor: 'var(--accent-blue)' }}
                  >
                    <Pin className="w-2.5 h-2.5" />
                    pinned
                  </Badge>
                )}
                <span className="ml-auto text-[10px]" style={{ color: 'var(--text-secondary)' }}>
                  {new Date(a.created_at).toLocaleTimeString()}
                </span>
              </div>
              <p className="text-xs leading-relaxed whitespace-pre-wrap" style={{ color: 'var(--text-primary)' }}>
                {a.content}
              </p>
            </div>
          ))
        )}
      </div>

      {/* Input area */}
      <div className="flex flex-col gap-1">
        {traceEventId && (
          <p className="text-[10px] flex items-center gap-1" style={{ color: 'var(--accent-blue)' }}>
            <Pin className="w-3 h-3" />
            Note will be pinned to trace event
          </p>
        )}
        <div className="flex gap-2 items-end">
          <Textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Add an investigation note… (Ctrl+Enter to save)"
            className="resize-none min-h-[60px] text-xs"
            disabled={submitting}
            maxLength={4096}
          />
          <Button
            size="sm"
            variant="default"
            onClick={handleSubmit}
            disabled={!draft.trim() || submitting}
            aria-label="Save annotation"
          >
            <Send className="w-3.5 h-3.5" />
          </Button>
        </div>
        {error && (
          <p className="text-xs" style={{ color: 'var(--accent-red)' }}>
            {error}
          </p>
        )}
        <p className="text-[10px]" style={{ color: 'var(--text-secondary)' }}>
          {draft.length}/4096
        </p>
      </div>
    </div>
  );
}
