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

// Short label for well-known types; falls back to the last path segment
const SHORT_TYPE: Record<string, string> = {
  'microsoft.compute/virtualmachines': 'VM',
  'microsoft.compute/disks': 'Disk',
  'microsoft.compute/snapshots': 'Snapshot',
  'microsoft.compute/images': 'Image',
  'microsoft.network/virtualnetworks': 'VNet',
  'microsoft.network/networksecuritygroups': 'NSG',
  'microsoft.network/publicipaddresses': 'Public IP',
  'microsoft.network/networkinterfaces': 'NIC',
  'microsoft.network/loadbalancers': 'Load Balancer',
  'microsoft.network/applicationgateways': 'App Gateway',
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
  'microsoft.insights/smartdetectoralertrules': 'Smart Detector',
  'microsoft.eventhub/namespaces': 'Event Hub',
  'microsoft.containerregistry/registries': 'ACR',
  'microsoft.web/sites': 'App Service',
  'microsoft.web/serverfarms': 'App Service Plan',
  'microsoft.sql/servers': 'SQL Server',
  'microsoft.sql/servers/databases': 'SQL Database',
  'microsoft.cache/redis': 'Redis',
  'microsoft.servicebus/namespaces': 'Service Bus',
  'microsoft.eventgrid/topics': 'Event Grid',
  'microsoft.fabric/capacities': 'Fabric Capacity',
};

function shortType(type: string): string {
  return SHORT_TYPE[type.toLowerCase()] ?? type.split('/').pop() ?? type;
}

const columns: TableColumnDefinition<Resource>[] = [
  createTableColumn<Resource>({
    columnId: 'name',
    renderHeaderCell: () => 'Name',
    renderCell: (item) => <TableCellLayout>{item.name}</TableCellLayout>,
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
    renderCell: (item) => <TableCellLayout>{item.location}</TableCellLayout>,
  }),
];

const ALL_TYPES = 'All types';

export function ResourcesTab({ subscriptions }: ResourcesTabProps) {
  const styles = useStyles();
  const [allResources, setAllResources] = useState<Resource[]>([]);
  const [availableTypes, setAvailableTypes] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState(ALL_TYPES);

  // Load all resources once — type filtering is done client-side
  const loadResources = useCallback(async () => {
    setLoading(true);
    setError(null);
    setTypeFilter(ALL_TYPES); // reset filter when subscriptions change
    try {
      const params = new URLSearchParams();
      if (subscriptions.length > 0) {
        params.set('subscriptions', subscriptions.join(','));
      }
      const res = await fetch(`/api/resources?${params.toString()}`);
      const data: { resources?: Resource[]; resourceTypes?: string[]; error?: string } =
        await res.json();
      if (data.error) {
        setError(data.error);
      } else {
        setAllResources(data.resources ?? []);
        setAvailableTypes(data.resourceTypes ?? []);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load resources');
    } finally {
      setLoading(false);
    }
  }, [subscriptions]);

  useEffect(() => {
    loadResources();
  }, [loadResources]);

  // Client-side filtering — no re-fetch on type/search change
  const filtered = allResources.filter((r) => {
    const matchesType =
      typeFilter === ALL_TYPES || r.type.toLowerCase() === typeFilter.toLowerCase();
    const q = search.toLowerCase();
    const matchesSearch =
      q === '' ||
      r.name.toLowerCase().includes(q) ||
      r.type.toLowerCase().includes(q) ||
      r.location.toLowerCase().includes(q);
    return matchesType && matchesSearch;
  });

  const handleTypeSelect = (_: SelectionEvents, data: OptionOnSelectData) => {
    setTypeFilter(data.optionValue ?? ALL_TYPES);
  };

  // Display value for the dropdown: show short label only
  const dropdownDisplay =
    typeFilter === ALL_TYPES ? ALL_TYPES : shortType(typeFilter);

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
          value={dropdownDisplay}
          onOptionSelect={handleTypeSelect}
        >
          <Option text={ALL_TYPES} key={ALL_TYPES} value={ALL_TYPES}>All types</Option>
          {availableTypes.map((t) => (
            <Option text={shortType(t)} key={t} value={t}>
              {shortType(t)}
            </Option>
          ))}
        </Dropdown>
        {!loading && (
          <Text size={200} className={styles.summary}>
            {filtered.length} of {allResources.length} resource{allResources.length !== 1 ? 's' : ''}
          </Text>
        )}
      </div>

      {loading && <Spinner label="Loading resources..." />}

      {error && !loading && (
        <Text className={styles.errorText}>{error}</Text>
      )}

      {!loading && !error && filtered.length === 0 && (
        <div className={styles.emptyState}>
          <ServerRegular className={styles.icon} />
          <Text weight="semibold">No resources found</Text>
          <Text size={200}>Try adjusting the subscription filter, type, or search query.</Text>
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
