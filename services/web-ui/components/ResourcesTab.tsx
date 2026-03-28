'use client';

import React, { useEffect, useState, useCallback } from 'react';
import {
  DataGrid,
  DataGridHeader,
  DataGridRow,
  DataGridHeaderCell,
  DataGridBody,
  DataGridCell,
  TableColumnDefinition,
  createTableColumn,
  TableCellLayout,
  Spinner,
  Text,
  Badge,
  Input,
  makeStyles,
  tokens,
  Dropdown,
  Option,
  SelectionEvents,
  OptionOnSelectData,
} from '@fluentui/react-components';
import { SearchRegular, ServerRegular } from '@fluentui/react-icons';

const useStyles = makeStyles({
  root: {
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalM,
    height: '100%',
  },
  toolbar: {
    display: 'flex',
    gap: tokens.spacingHorizontalS,
    alignItems: 'center',
    flexWrap: 'wrap',
  },
  searchInput: {
    maxWidth: '280px',
    flex: 1,
  },
  summary: {
    color: tokens.colorNeutralForeground3,
  },
  emptyState: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    padding: tokens.spacingVerticalXXL,
    gap: tokens.spacingVerticalM,
    color: tokens.colorNeutralForeground3,
  },
  icon: {
    fontSize: '32px',
  },
  typeCell: {
    fontFamily: 'monospace',
    fontSize: '12px',
    color: tokens.colorNeutralForeground2,
  },
  errorText: {
    color: tokens.colorPaletteRedForeground1,
  },
});

interface Resource {
  id: string;
  name: string;
  type: string;
  location: string;
}

interface ResourcesTabProps {
  subscriptions: string[];
}

// Derive a short resource type label: Microsoft.Compute/virtualMachines → VM
const SHORT_TYPE: Record<string, string> = {
  'microsoft.compute/virtualmachines': 'VM',
  'microsoft.compute/disks': 'Disk',
  'microsoft.network/virtualnetworks': 'VNet',
  'microsoft.network/networksecuritygroups': 'NSG',
  'microsoft.network/publicipaddresses': 'Public IP',
  'microsoft.network/networkinterfaces': 'NIC',
  'microsoft.storage/storageaccounts': 'Storage',
  'microsoft.keyvault/vaults': 'Key Vault',
  'microsoft.containerservice/managedclusters': 'AKS',
  'microsoft.app/containerapps': 'Container App',
  'microsoft.app/managedenvironments': 'CAE',
  'microsoft.documentdb/databaseaccounts': 'Cosmos DB',
  'microsoft.dbforpostgresql/flexibleservers': 'PostgreSQL',
  'microsoft.cognitiveservices/accounts': 'AI/Foundry',
  'microsoft.operationalinsights/workspaces': 'Log Analytics',
  'microsoft.insights/components': 'App Insights',
  'microsoft.eventhub/namespaces': 'Event Hub',
  'microsoft.containerregistry/registries': 'ACR',
};

function shortType(type: string): string {
  return SHORT_TYPE[type.toLowerCase()] ?? type.split('/').pop() ?? type;
}

const RESOURCE_TYPES = [
  'All types',
  'Microsoft.Compute/virtualMachines',
  'Microsoft.Network/virtualNetworks',
  'Microsoft.Storage/storageAccounts',
  'Microsoft.App/containerApps',
  'Microsoft.ContainerService/managedClusters',
  'Microsoft.KeyVault/vaults',
  'Microsoft.DocumentDB/databaseAccounts',
];

const columns: TableColumnDefinition<Resource>[] = [
  createTableColumn<Resource>({
    columnId: 'name',
    renderHeaderCell: () => 'Name',
    renderCell: (item) => (
      <TableCellLayout>{item.name}</TableCellLayout>
    ),
  }),
  createTableColumn<Resource>({
    columnId: 'type',
    renderHeaderCell: () => 'Type',
    renderCell: (item) => (
      <TableCellLayout>
        <Badge appearance="tint" color="informative" size="small">
          {shortType(item.type)}
        </Badge>
      </TableCellLayout>
    ),
  }),
  createTableColumn<Resource>({
    columnId: 'location',
    renderHeaderCell: () => 'Location',
    renderCell: (item) => (
      <TableCellLayout>{item.location}</TableCellLayout>
    ),
  }),
];

export function ResourcesTab({ subscriptions }: ResourcesTabProps) {
  const styles = useStyles();
  const [resources, setResources] = useState<Resource[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('All types');

  const loadResources = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (subscriptions.length > 0) {
        params.set('subscriptions', subscriptions.join(','));
      }
      if (typeFilter && typeFilter !== 'All types') {
        params.set('type', typeFilter);
      }
      const res = await fetch(`/api/resources?${params.toString()}`);
      const data: { resources?: Resource[]; error?: string } = await res.json();
      if (data.error) {
        setError(data.error);
      } else {
        setResources(data.resources ?? []);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load resources');
    } finally {
      setLoading(false);
    }
  }, [subscriptions, typeFilter]);

  useEffect(() => {
    loadResources();
  }, [loadResources]);

  const filtered = resources.filter((r) =>
    search === '' ||
    r.name.toLowerCase().includes(search.toLowerCase()) ||
    r.type.toLowerCase().includes(search.toLowerCase()) ||
    r.location.toLowerCase().includes(search.toLowerCase())
  );

  const handleTypeSelect = (_: SelectionEvents, data: OptionOnSelectData) => {
    setTypeFilter(data.optionValue ?? 'All types');
  };

  return (
    <div className={styles.root}>
      <div className={styles.toolbar}>
        <Input
          className={styles.searchInput}
          placeholder="Search resources..."
          contentBefore={<SearchRegular />}
          value={search}
          onChange={(_, d) => setSearch(d.value)}
        />
        <Dropdown
          placeholder="All types"
          value={typeFilter}
          onOptionSelect={handleTypeSelect}
        >
          {RESOURCE_TYPES.map((t) => (
            <Option key={t} value={t}>{t === 'All types' ? 'All types' : shortType(t)}</Option>
          ))}
        </Dropdown>
        {!loading && (
          <Text size={200} className={styles.summary}>
            {filtered.length} of {resources.length} resource{resources.length !== 1 ? 's' : ''}
          </Text>
        )}
      </div>

      {loading && (
        <Spinner label="Loading resources..." />
      )}

      {error && !loading && (
        <Text className={styles.errorText}>{error}</Text>
      )}

      {!loading && !error && filtered.length === 0 && (
        <div className={styles.emptyState}>
          <ServerRegular className={styles.icon} />
          <Text weight="semibold">No resources found</Text>
          <Text size={200}>Try adjusting the subscription filter or search query.</Text>
        </div>
      )}

      {!loading && !error && filtered.length > 0 && (
        <DataGrid
          items={filtered}
          columns={columns}
          getRowId={(item) => item.id}
          sortable
        >
          <DataGridHeader>
            <DataGridRow>
              {({ renderHeaderCell }) => (
                <DataGridHeaderCell>{renderHeaderCell()}</DataGridHeaderCell>
              )}
            </DataGridRow>
          </DataGridHeader>
          <DataGridBody<Resource>>
            {({ item, rowId }) => (
              <DataGridRow<Resource> key={rowId}>
                {({ renderCell }) => (
                  <DataGridCell>{renderCell(item)}</DataGridCell>
                )}
              </DataGridRow>
            )}
          </DataGridBody>
        </DataGrid>
      )}
    </div>
  );
}
