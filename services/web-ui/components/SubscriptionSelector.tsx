'use client';

import React, { useEffect, useState } from 'react';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command';
import { Checkbox } from '@/components/ui/checkbox';
import { Button } from '@/components/ui/button';
import { ChevronsUpDown, Loader2 } from 'lucide-react';

interface Subscription {
  id: string;
  name: string;
}

interface SubscriptionSelectorProps {
  selected: string[];
  onChange: (ids: string[]) => void;
  onLoad?: (ids: string[]) => void;
  trigger?: React.ReactNode;
}

export function SubscriptionSelector({ selected, onChange, onLoad, trigger }: SubscriptionSelectorProps) {
  const [subscriptions, setSubscriptions] = useState<Subscription[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetch('/api/subscriptions')
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json()
      })
      .then((data: { subscriptions?: Subscription[]; error?: string }) => {
        if (data.subscriptions) {
          setSubscriptions(data.subscriptions);
          // Auto-select all subscriptions on first load so the agent has context
          if (onLoad && data.subscriptions.length > 0) {
            onLoad(data.subscriptions.map((s) => s.id));
          }
        }
      })
      .catch(() => {
        setError(true)
      })
      .finally(() => setLoading(false));
  // onLoad intentionally excluded — only run once on mount
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleToggle = (id: string) => {
    const next = selected.includes(id)
      ? selected.filter((s) => s !== id)
      : [...selected, id];
    onChange(next);
  };

  return (
    <div className="flex items-center gap-2">
      <span className="text-sm text-muted-foreground">
        Showing results for {selected.length > 0 ? selected.length : 'all'} subscription(s)
      </span>

      {error && (
        <span className="text-xs" style={{ color: 'var(--accent-red)' }}>
          Failed to load subscriptions
        </span>
      )}

      {loading ? (
        <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          Loading subscriptions...
        </div>
      ) : (
        <Popover open={open} onOpenChange={setOpen}>
          <PopoverTrigger asChild>
            {trigger ?? (
              <button className="flex items-center gap-2 rounded-md border border-input px-3 py-1.5 text-sm bg-background hover:bg-accent">
                Filter subscriptions...
                <ChevronsUpDown className="h-3.5 w-3.5 opacity-50" />
              </button>
            )}
          </PopoverTrigger>
          <PopoverContent className="w-[280px] p-0">
            <Command>
              <CommandInput placeholder="Search subscriptions..." />
              <CommandList>
                <CommandEmpty>No subscriptions found.</CommandEmpty>
                <CommandGroup>
                  {subscriptions.map((sub) => (
                    <CommandItem
                      key={sub.id}
                      value={sub.name}
                      onSelect={() => handleToggle(sub.id)}
                      className="flex items-center gap-2"
                    >
                      <Checkbox
                        checked={selected.includes(sub.id)}
                        onCheckedChange={() => handleToggle(sub.id)}
                      />
                      {sub.name}
                    </CommandItem>
                  ))}
                </CommandGroup>
              </CommandList>
            </Command>
          </PopoverContent>
        </Popover>
      )}
    </div>
  );
}
