'use client';

import React from 'react';
import { Dropdown, Option, makeStyles } from '@fluentui/react-components';

const useStyles = makeStyles({
  root: {
    width: '160px',
  },
});

interface TimeRangeSelectorProps {
  value: string;
  onChange: (value: string) => void;
}

const OPTIONS = [
  { value: '1h', label: 'Last 1 hour' },
  { value: '6h', label: 'Last 6 hours' },
  { value: '24h', label: 'Last 24 hours' },
  { value: '7d', label: 'Last 7 days' },
];

export function TimeRangeSelector({ value, onChange }: TimeRangeSelectorProps) {
  const styles = useStyles();

  return (
    <Dropdown
      className={styles.root}
      value={OPTIONS.find((o) => o.value === value)?.label || 'Last 1 hour'}
      selectedOptions={[value]}
      onOptionSelect={(_, data) => {
        if (data.optionValue) {
          onChange(data.optionValue);
        }
      }}
      aria-label="Time range"
    >
      {OPTIONS.map((opt) => (
        <Option key={opt.value} value={opt.value}>
          {opt.label}
        </Option>
      ))}
    </Dropdown>
  );
}
