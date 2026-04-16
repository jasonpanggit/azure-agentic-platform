'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useResizable } from '@/lib/use-resizable';
import { X, Users, Zap, FileText } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { cn } from '@/lib/utils';
import { AvatarGroup, WarRoomParticipant } from './AvatarGroup';
import { AnnotationLayer, Annotation } from './AnnotationLayer';

interface WarRoomPanelProps {
  incidentId: string;
  incidentTitle?: string;
  onClose: () => void;
}

interface WarRoomState {
  participants: WarRoomParticipant[];
  annotations: Annotation[];
  handoff_summary: string | null;
  loading: boolean;
  error: string | null;
}

const HEARTBEAT_INTERVAL_MS = 30_000; // 30 seconds

/**
 * WarRoomPanel — slide-over sheet for multi-operator P0 incident collaboration.
 *
 * On mount:
 *  1. POST /api/proxy/war-room/join to join the war room
 *  2. Connect SSE stream via GET /api/proxy/war-room/stream for live annotation push
 *  3. Start 30s heartbeat interval to maintain presence
 *
 * On unmount: closes SSE connection, clears heartbeat interval.
 */
export function WarRoomDetailPanel({ incidentId, incidentTitle, onClose }: WarRoomPanelProps) {
  const [state, setState] = useState<WarRoomState>({
    participants: [],
    annotations: [],
    handoff_summary: null,
    loading: true,
    error: null,
  });
  const [generatingHandoff, setGeneratingHandoff] = useState(false);
  const [handoffError, setHandoffError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ----- Join war room on mount -----
  const joinWarRoom = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const res = await fetch(
        `/api/proxy/war-room/join?incident_id=${encodeURIComponent(incidentId)}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ role: 'support' }),
        }
      );
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.error ?? `Join failed: ${res.status}`);
      }
      const data = await res.json();
      const warRoom = data.war_room ?? {};
      setState({
        participants: (warRoom.participants as WarRoomParticipant[]) ?? [],
        annotations: (warRoom.annotations as Annotation[]) ?? [],
        handoff_summary: warRoom.handoff_summary ?? null,
        loading: false,
        error: null,
      });
    } catch (err) {
      setState((s) => ({
        ...s,
        loading: false,
        error: err instanceof Error ? err.message : 'Failed to join war room',
      }));
    }
  }, [incidentId]);

  // ----- Connect SSE stream -----
  const connectStream = useCallback(() => {
    const controller = new AbortController();
    abortRef.current = controller;

    (async () => {
      try {
        const res = await fetch(
          `/api/proxy/war-room/stream?incident_id=${encodeURIComponent(incidentId)}`,
          { signal: controller.signal }
        );
        if (!res.ok || !res.body) return;

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          const lines = buffer.split('\n');
          buffer = lines.pop() ?? '';

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const payload = JSON.parse(line.slice(6));
                if (payload.type === 'annotation' && payload.annotation) {
                  setState((s) => ({
                    ...s,
                    annotations: [...s.annotations, payload.annotation as Annotation],
                  }));
                }
              } catch {
                // Malformed SSE data — skip
              }
            }
          }
        }
      } catch (err) {
        if ((err as Error)?.name !== 'AbortError') {
          console.error('[WarRoomPanel] SSE stream error:', err);
        }
      }
    })();
  }, [incidentId]);

  // ----- Heartbeat -----
  const startHeartbeat = useCallback(() => {
    heartbeatRef.current = setInterval(async () => {
      try {
        await fetch(
          `/api/proxy/war-room/heartbeat?incident_id=${encodeURIComponent(incidentId)}`,
          { method: 'POST' }
        );
      } catch {
        // Heartbeat is best-effort — swallow errors silently
      }
    }, HEARTBEAT_INTERVAL_MS);
  }, [incidentId]);

  useEffect(() => {
    joinWarRoom();
    connectStream();
    startHeartbeat();

    return () => {
      abortRef.current?.abort();
      if (heartbeatRef.current) clearInterval(heartbeatRef.current);
    };
  }, [joinWarRoom, connectStream, startHeartbeat]);

  // ----- Annotation added locally (optimistic append for annotations from this client) -----
  function handleAnnotationAdded(annotation: Annotation) {
    setState((s) => ({
      ...s,
      // Avoid duplicate if SSE already pushed this annotation
      annotations: s.annotations.some((a) => a.id === annotation.id)
        ? s.annotations
        : [...s.annotations, annotation],
    }));
  }

  // ----- Generate handoff summary -----
  async function handleGenerateHandoff() {
    setGeneratingHandoff(true);
    setHandoffError(null);
    try {
      const res = await fetch(
        `/api/proxy/war-room/handoff?incident_id=${encodeURIComponent(incidentId)}`,
        { method: 'POST' }
      );
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.error ?? `Handoff failed: ${res.status}`);
      }
      const data = await res.json();
      setState((s) => ({ ...s, handoff_summary: data.summary ?? null }));
    } catch (err) {
      setHandoffError(err instanceof Error ? err.message : 'Failed to generate handoff');
    } finally {
      setGeneratingHandoff(false);
    }
  }

    // Panel resize
  const { width: panelWidth, onMouseDown: resizeOnMouseDown } = useResizable({
    minWidth: 380,
    maxWidth: 900,
    defaultWidth: 480,
    storageKey: 'war-room-panel-width',
  })

  // Drag-to-reposition
  const [position, setPosition] = useState<{ x: number; y: number } | null>(null)
  const reposDragState = useRef({ isDragging: false, startX: 0, startY: 0, originX: 0, originY: 0 })

  const handleHeaderMouseDown = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (e.button !== 0) return
    e.preventDefault()
    reposDragState.current = {
      isDragging: true,
      startX: e.clientX,
      startY: e.clientY,
      originX: position?.x ?? 0,
      originY: position?.y ?? 0,
    }
  }, [position])

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (!reposDragState.current.isDragging) return
      const dx = e.clientX - reposDragState.current.startX
      const dy = e.clientY - reposDragState.current.startY
      setPosition({ x: reposDragState.current.originX + dx, y: reposDragState.current.originY + dy })
    }
    const onMouseUp = () => { reposDragState.current.isDragging = false }
    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)
    return () => {
      document.removeEventListener('mousemove', onMouseMove)
      document.removeEventListener('mouseup', onMouseUp)
    }
  }, [])

  return (
    <div
      className="fixed inset-y-0 right-0 z-50 flex flex-col overflow-hidden shadow-2xl"
      style={{ width: `${panelWidth}px`, background: 'var(--bg-canvas)', borderLeft: '1px solid var(--border)', transform: position ? `translate(${position.x}px, ${position.y}px)` : undefined }}
      role="dialog"
      aria-label={`War Room — ${incidentTitle ?? incidentId}`}
    >
      {/* Resize handle */}
      <div className="absolute left-0 top-0 bottom-0 w-1.5 z-10 cursor-col-resize hover:bg-primary/20 transition-colors" onMouseDown={resizeOnMouseDown} />
      {/* Header — drag handle */}
      <div
        className="flex items-center gap-3 px-4 py-3 shrink-0 select-none"
        style={{ borderBottom: '1px solid var(--border)', cursor: 'grab' }}
        onMouseDown={handleHeaderMouseDown}
      >
        <Zap className="w-4 h-4 shrink-0" style={{ color: 'var(--accent-red)' }} />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold truncate" style={{ color: 'var(--text-primary)' }}>
            War Room
          </p>
          <p className="text-xs truncate" style={{ color: 'var(--text-secondary)' }}>
            {incidentTitle ?? incidentId}
          </p>
        </div>
        {!state.loading && (
          <AvatarGroup
            participants={state.participants}
            className="shrink-0"
          />
        )}
        <Button variant="ghost" size="icon" onClick={onClose} onMouseDown={(e) => e.stopPropagation()} aria-label="Close war room">
          <X className="w-4 h-4" />
        </Button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-hidden">
        {state.loading ? (
          <div className="p-4 flex flex-col gap-3">
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-3/4" />
            <Skeleton className="h-24 w-full" />
          </div>
        ) : state.error ? (
          <div className="p-4">
            <p className="text-sm" style={{ color: 'var(--accent-red)' }}>{state.error}</p>
            <Button size="sm" variant="outline" className="mt-2" onClick={joinWarRoom}>
              Retry
            </Button>
          </div>
        ) : (
          <Tabs defaultValue="notes" className="h-full flex flex-col">
            <TabsList className="mx-4 mt-3 shrink-0 w-auto justify-start">
              <TabsTrigger value="notes" className="text-xs gap-1">
                <FileText className="w-3 h-3" />
                Notes
                {state.annotations.length > 0 && (
                  <Badge
                    variant="secondary"
                    className="ml-1 px-1 py-0 text-[10px]"
                  >
                    {state.annotations.length}
                  </Badge>
                )}
              </TabsTrigger>
              <TabsTrigger value="presence" className={cn('text-xs gap-1')}>
                <Users className="w-3 h-3" />
                Team ({state.participants.length})
              </TabsTrigger>
              <TabsTrigger value="handoff" className="text-xs">
                Handoff
              </TabsTrigger>
            </TabsList>

            {/* Notes tab */}
            <TabsContent value="notes" className="flex-1 overflow-y-auto p-4">
              <AnnotationLayer
                incidentId={incidentId}
                annotations={state.annotations}
                onAnnotationAdded={handleAnnotationAdded}
              />
            </TabsContent>

            {/* Presence tab */}
            <TabsContent value="presence" className="flex-1 overflow-y-auto p-4">
              <div className="flex flex-col gap-2">
                {state.participants.map((p) => (
                  <div
                    key={p.operator_id}
                    className="flex items-center gap-3 rounded-md px-3 py-2"
                    style={{ background: 'color-mix(in srgb, var(--accent-blue) 6%, var(--bg-canvas))', border: '1px solid var(--border)' }}
                  >
                    <span className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>
                      {p.display_name || p.operator_id}
                    </span>
                    <Badge
                      variant="outline"
                      className="text-[10px] px-1.5"
                      style={{
                        color: p.role === 'lead' ? 'var(--accent-yellow, #f59e0b)' : 'var(--accent-blue)',
                        borderColor: p.role === 'lead' ? 'var(--accent-yellow, #f59e0b)' : 'var(--accent-blue)',
                      }}
                    >
                      {p.role}
                    </Badge>
                    <span className="ml-auto text-[10px]" style={{ color: 'var(--text-secondary)' }}>
                      joined {new Date(p.joined_at).toLocaleTimeString()}
                    </span>
                  </div>
                ))}
              </div>
            </TabsContent>

            {/* Handoff tab */}
            <TabsContent value="handoff" className="flex-1 overflow-y-auto p-4 flex flex-col gap-3">
              <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                Generate a structured shift-handoff summary using GPT-4o based on all investigation notes.
              </p>
              <Button
                size="sm"
                onClick={handleGenerateHandoff}
                disabled={generatingHandoff}
                className="self-start"
              >
                {generatingHandoff ? 'Generating…' : 'End my shift — generate handoff'}
              </Button>
              {handoffError && (
                <p className="text-xs" style={{ color: 'var(--accent-red)' }}>{handoffError}</p>
              )}
              {state.handoff_summary && (
                <div
                  className="rounded-md p-3 text-xs leading-relaxed whitespace-pre-wrap font-mono"
                  style={{
                    background: 'color-mix(in srgb, var(--accent-blue) 6%, var(--bg-canvas))',
                    border: '1px solid var(--border)',
                    color: 'var(--text-primary)',
                  }}
                >
                  {state.handoff_summary}
                </div>
              )}
            </TabsContent>
          </Tabs>
        )}
      </div>
    </div>
  );
}
