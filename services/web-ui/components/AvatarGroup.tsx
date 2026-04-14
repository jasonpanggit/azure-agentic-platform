'use client';

import React from 'react';
import { cn } from '@/lib/utils';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';

export interface WarRoomParticipant {
  operator_id: string;
  display_name: string;
  role: 'lead' | 'support';
  joined_at: string;
  last_seen_at: string;
}

interface AvatarGroupProps {
  participants: WarRoomParticipant[];
  /** Threshold in seconds; participants with last_seen_at older than this are shown as offline. Default: 60 */
  onlineThresholdSeconds?: number;
  className?: string;
}

/**
 * AvatarGroup — shows initials badges for war room participants.
 *
 * Online = last_seen_at within onlineThresholdSeconds (default 60s).
 * Lead operator gets a gold ring; support operators get the standard ring.
 * Dark-mode-safe: uses CSS semantic tokens only.
 */
export function AvatarGroup({
  participants,
  onlineThresholdSeconds = 60,
  className,
}: AvatarGroupProps) {
  const now = Date.now();

  function isOnline(p: WarRoomParticipant): boolean {
    const lastSeen = new Date(p.last_seen_at).getTime();
    return (now - lastSeen) / 1000 < onlineThresholdSeconds;
  }

  function getInitials(p: WarRoomParticipant): string {
    const name = p.display_name || p.operator_id;
    return name
      .split(/[\s@._-]+/)
      .filter(Boolean)
      .map((part) => part[0]?.toUpperCase() ?? '')
      .slice(0, 2)
      .join('');
  }

  if (participants.length === 0) {
    return (
      <span className={cn('text-xs', className)} style={{ color: 'var(--text-secondary)' }}>
        No participants
      </span>
    );
  }

  return (
    <TooltipProvider>
      <div className={cn('flex -space-x-2', className)}>
        {participants.map((p) => {
          const online = isOnline(p);
          const isLead = p.role === 'lead';
          return (
            <Tooltip key={p.operator_id}>
              <TooltipTrigger asChild>
                <div
                  className="relative w-8 h-8 rounded-full flex items-center justify-center text-xs font-semibold cursor-default select-none border-2"
                  style={{
                    background: 'color-mix(in srgb, var(--accent-blue) 20%, var(--bg-canvas))',
                    color: 'var(--accent-blue)',
                    borderColor: isLead ? 'var(--accent-yellow, #f59e0b)' : 'var(--border)',
                    opacity: online ? 1 : 0.45,
                  }}
                  aria-label={`${p.display_name || p.operator_id} (${p.role}${online ? '' : ', offline'})`}
                >
                  {getInitials(p)}
                  {/* Online indicator dot */}
                  {online && (
                    <span
                      className="absolute bottom-0 right-0 w-2 h-2 rounded-full border border-white"
                      style={{ background: 'var(--accent-green, #22c55e)' }}
                    />
                  )}
                </div>
              </TooltipTrigger>
              <TooltipContent side="bottom">
                <p className="font-medium">{p.display_name || p.operator_id}</p>
                <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                  {p.role} · {online ? 'online' : 'offline'}
                </p>
              </TooltipContent>
            </Tooltip>
          );
        })}
      </div>
    </TooltipProvider>
  );
}
