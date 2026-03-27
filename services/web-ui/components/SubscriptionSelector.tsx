'use client';

import React from 'react';
import {
  Combobox,
  Option,
  makeStyles,
  tokens,
  Text,
} from '@fluentui/react-components';

const useStyles = makeStyles({
  root: {
    display: 'flex',
    alignItems: 'center',
    gap: tokens.spacingHorizontalS,
  },
});

interface SubscriptionSelectorProps {
  selected: string[];
  onChange: (ids: string[]) => void;
}

// Placeholder subscriptions — replaced by real data from Azure in integration
const PLACEHOLDER_SUBSCRIPTIONS = [
  { id: 'sub-platform-001', name: 'Platform (dev)' },
  { id: 'sub-compute-001', name: 'Compute (dev)' },
  { id: 'sub-network-001', name: 'Network (dev)' },
];

export function SubscriptionSelector({ selected, onChange }: SubscriptionSelectorProps) {
  const styles = useStyles();

  const handleSelect = (_: unknown, data: { selectedOptions: string[] }) => {
    onChange(data.selectedOptions);
  };

  return (
    <div className={styles.root}>
      <Text size={200}>
        Showing results for {selected.length || 'all'} subscription(s)
      </Text>
      <Combobox
        multiselect
        placeholder="Filter subscriptions..."
        selectedOptions={selected}
        onOptionSelect={handleSelect}
      >
        {PLACEHOLDER_SUBSCRIPTIONS.map((sub) => (
          <Option key={sub.id} value={sub.id}>
            {sub.name}
          </Option>
        ))}
      </Combobox>
    </div>
  );
}
