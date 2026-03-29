'use client';

import React, { useState } from 'react';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import { Badge } from '@/components/ui/badge';
import { ChevronRight, Wrench, ArrowRight, ShieldCheck } from 'lucide-react';

export interface TraceEvent {
  type: 'tool_call' | 'handoff' | 'approval_gate' | 'error';
  seq: number;
  name: string;
  durationMs?: number;
  status: 'success' | 'error' | 'pending';
  payload: Record<string, unknown>;
}

interface TraceTreeProps {
  events: TraceEvent[];
}

const typeIcons: Record<string, React.ReactElement> = {
  tool_call: <Wrench className="h-3.5 w-3.5" />,
  handoff: <ArrowRight className="h-3.5 w-3.5" />,
  approval_gate: <ShieldCheck className="h-3.5 w-3.5" />,
};

const statusVariant: Record<string, 'default' | 'destructive' | 'outline' | 'secondary'> = {
  success: 'default',
  error: 'destructive',
  pending: 'outline',
};

function TraceEventNode({ event }: { event: TraceEvent }) {
  const [showPayload, setShowPayload] = useState(false);
  const icon = typeIcons[event.type] ?? typeIcons.tool_call;

  return (
    <div>
      <div
        className="flex items-center gap-2 py-1 px-2 text-sm rounded-sm hover:bg-muted cursor-pointer"
        onClick={() => setShowPayload(!showPayload)}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => e.key === 'Enter' && setShowPayload(!showPayload)}
      >
        {icon}
        <span className="flex-1">{event.name}</span>
        {event.durationMs !== undefined && (
          <span className="text-xs text-muted-foreground">{event.durationMs}ms</span>
        )}
        <Badge variant={statusVariant[event.status] ?? 'outline'}>
          {event.status}
        </Badge>
      </div>
      {showPayload && (
        <pre className="font-mono text-[12px] whitespace-pre-wrap p-2 bg-muted rounded-md max-h-[150px] overflow-auto mx-2 mb-1">
          {JSON.stringify(event.payload, null, 2)}
        </pre>
      )}
    </div>
  );
}

export function TraceTree({ events }: TraceTreeProps) {
  const [expanded, setExpanded] = useState(false);

  if (events.length === 0) return null;

  return (
    <div className="border-t border-border max-h-[200px] overflow-auto p-2">
      <Collapsible open={expanded} onOpenChange={setExpanded}>
        <CollapsibleTrigger className="cursor-pointer py-1 text-sm font-semibold text-muted-foreground hover:text-foreground flex items-center gap-1">
          <ChevronRight
            className={`h-3.5 w-3.5 transition-transform ${expanded ? 'rotate-90' : ''}`}
          />
          Agent Trace ({events.length} events)
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="mt-1">
            {events.map((event) => (
              <TraceEventNode key={event.seq} event={event} />
            ))}
          </div>
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
}
