'use client';

import React, { useEffect, useState } from 'react';
import {
  Combobox,
  Option,
  Spinner,
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

interface Subscription {
  id: string;
  name: string;
}

interface SubscriptionSelectorProps {
  selected: string[];
  onChange: (ids: string[]) => void;
}

export function SubscriptionSelector({ selected, onChange }: SubscriptionSelectorProps) {
  const styles = useStyles();
  const [subscriptions, setSubscriptions] = useState<Subscription[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/api/subscriptions')
      .then((res) => res.json())
      .then((data: { subscriptions?: Subscription[]; error?: string }) => {
        if (data.subscriptions) {
          setSubscriptions(data.subscriptions);
        }
      })
      .catch(() => {
        // Silently fail — selector stays empty
      })
      .finally(() => setLoading(false));
  }, []);

  const handleSelect = (_: unknown, data: { selectedOptions: string[] }) => {
    onChange(data.selectedOptions);
  };

  return (
    <div className={styles.root}>
      <Text size={200}>
        Showing results for {selected.length > 0 ? selected.length : 'all'} subscription(s)
      </Text>
      {loading ? (
        <Spinner size="tiny" label="Loading subscriptions..." labelPosition="after" />
      ) : (
        <Combobox
          multiselect
          placeholder="Filter subscriptions..."
          selectedOptions={selected}
          onOptionSelect={handleSelect}
        >
          {subscriptions.map((sub) => (
            <Option key={sub.id} value={sub.id}>
              {sub.name}
            </Option>
          ))}
        </Combobox>
      )}
    </div>
  );
}
