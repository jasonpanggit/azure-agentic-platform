'use client';

import React from 'react';
import {
  Toolbar,
  Dropdown,
  Option,
  makeStyles,
  tokens,
} from '@fluentui/react-components';

const useStyles = makeStyles({
  root: {
    display: 'flex',
    gap: tokens.spacingHorizontalS,
    alignItems: 'center',
    flexWrap: 'wrap',
  },
});

interface FilterState {
  severity?: string;
  domain?: string;
  status?: string;
}

interface AlertFiltersProps {
  filters: FilterState;
  onChange: (filters: FilterState) => void;
}

export function AlertFilters({ filters, onChange }: AlertFiltersProps) {
  const styles = useStyles();

  return (
    <Toolbar className={styles.root}>
      <Dropdown
        placeholder="Severity"
        value={filters.severity || ''}
        onOptionSelect={(_, data) => onChange({ ...filters, severity: data.optionValue as string })}
      >
        <Option value="">All</Option>
        <Option value="Sev0">Sev0</Option>
        <Option value="Sev1">Sev1</Option>
        <Option value="Sev2">Sev2</Option>
        <Option value="Sev3">Sev3</Option>
      </Dropdown>

      <Dropdown
        placeholder="Domain"
        value={filters.domain || ''}
        onOptionSelect={(_, data) => onChange({ ...filters, domain: data.optionValue as string })}
      >
        <Option value="">All</Option>
        <Option value="compute">Compute</Option>
        <Option value="network">Network</Option>
        <Option value="storage">Storage</Option>
        <Option value="security">Security</Option>
        <Option value="arc">Arc</Option>
        <Option value="sre">SRE</Option>
      </Dropdown>

      <Dropdown
        placeholder="Status"
        value={filters.status || ''}
        onOptionSelect={(_, data) => onChange({ ...filters, status: data.optionValue as string })}
      >
        <Option value="">All</Option>
        <Option value="new">New</Option>
        <Option value="acknowledged">Acknowledged</Option>
        <Option value="closed">Closed</Option>
      </Dropdown>
    </Toolbar>
  );
}
