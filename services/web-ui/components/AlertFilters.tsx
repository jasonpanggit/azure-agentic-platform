'use client';

import React from 'react';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

interface FilterState {
  severity?: string;
  domain?: string;
  status?: string;
}

interface AlertFiltersProps {
  filters: FilterState;
  onChange: (filters: FilterState) => void;
}

// Radix Select forbids empty-string values — use 'all' as the "no filter" sentinel.
const toSelectValue = (v: string | undefined) => v || 'all';
const fromSelectValue = (v: string) => (v === 'all' ? undefined : v);

export function AlertFilters({ filters, onChange }: AlertFiltersProps) {
  return (
    <div className="flex gap-2 items-center flex-wrap">
      <Select
        value={toSelectValue(filters.severity)}
        onValueChange={(value) => onChange({ ...filters, severity: fromSelectValue(value) })}
      >
        <SelectTrigger className="w-[140px]">
          <SelectValue placeholder="Severity" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All</SelectItem>
          <SelectItem value="Sev0">Sev0</SelectItem>
          <SelectItem value="Sev1">Sev1</SelectItem>
          <SelectItem value="Sev2">Sev2</SelectItem>
          <SelectItem value="Sev3">Sev3</SelectItem>
        </SelectContent>
      </Select>

      <Select
        value={toSelectValue(filters.domain)}
        onValueChange={(value) => onChange({ ...filters, domain: fromSelectValue(value) })}
      >
        <SelectTrigger className="w-[140px]">
          <SelectValue placeholder="Domain" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All</SelectItem>
          <SelectItem value="compute">Compute</SelectItem>
          <SelectItem value="network">Network</SelectItem>
          <SelectItem value="storage">Storage</SelectItem>
          <SelectItem value="security">Security</SelectItem>
          <SelectItem value="arc">Arc</SelectItem>
          <SelectItem value="sre">SRE</SelectItem>
        </SelectContent>
      </Select>

      <Select
        value={toSelectValue(filters.status)}
        onValueChange={(value) => onChange({ ...filters, status: fromSelectValue(value) })}
      >
        <SelectTrigger className="w-[140px]">
          <SelectValue placeholder="Status" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All</SelectItem>
          <SelectItem value="new">New</SelectItem>
          <SelectItem value="acknowledged">Acknowledged</SelectItem>
          <SelectItem value="closed">Closed</SelectItem>
        </SelectContent>
      </Select>
    </div>
  );
}
