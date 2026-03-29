'use client';

import React from 'react';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

interface TimeRangeSelectorProps {
  value: string;
  onChange: (value: string) => void;
}

export function TimeRangeSelector({ value, onChange }: TimeRangeSelectorProps) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className="w-[120px]">
        <SelectValue placeholder="Time range" />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="1h">Last 1 hour</SelectItem>
        <SelectItem value="6h">Last 6 hours</SelectItem>
        <SelectItem value="24h">Last 24 hours</SelectItem>
        <SelectItem value="7d">Last 7 days</SelectItem>
      </SelectContent>
    </Select>
  );
}
