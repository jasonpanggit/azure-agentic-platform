'use client';

import React, { useEffect, useState, useCallback } from 'react';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Search, Server } from 'lucide-react';

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

const ALL_TYPES = 'All types';

export function ResourcesTab({ subscriptions }: ResourcesTabProps) {
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
      const res = await fetch(`/api/proxy/resources?${params.toString()}`);
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

  return (
    <div className="flex flex-col gap-4 h-full">
      <div className="flex gap-2 items-center flex-wrap">
        <div className="relative flex-1 max-w-[280px]">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <Input
            className="pl-8"
            placeholder="Search resources..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        <Select value={typeFilter} onValueChange={(value) => setTypeFilter(value)}>
          <SelectTrigger className="w-[160px]">
            <SelectValue placeholder="All types" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_TYPES}>All types</SelectItem>
            {availableTypes.map((t) => (
              <SelectItem key={t} value={t}>
                {shortType(t)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {!loading && (
          <p className="text-sm text-muted-foreground">
            {filtered.length} of {allResources.length} resource{allResources.length !== 1 ? 's' : ''}
          </p>
        )}
      </div>

      {loading && (
        <div className="flex flex-col gap-1">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      )}

      {error && !loading && (
        <p className="text-sm text-destructive">{error}</p>
      )}

      {!loading && !error && filtered.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16 gap-3 text-muted-foreground">
          <Server className="h-8 w-8" />
          <p className="font-semibold text-foreground">No resources found</p>
          <p className="text-sm">Try adjusting the subscription filter, type, or search query.</p>
        </div>
      )}

      {!loading && !error && filtered.length > 0 && (
        <div className="rounded-md border overflow-hidden">
          <Table className="w-full text-sm">
            <TableHeader>
              <TableRow>
                <TableHead className="h-10 px-3 text-left font-semibold text-muted-foreground">Name</TableHead>
                <TableHead className="h-10 px-3 text-left font-semibold text-muted-foreground">Type</TableHead>
                <TableHead className="h-10 px-3 text-left font-semibold text-muted-foreground">Location</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((item) => (
                <TableRow key={item.id} className="border-b hover:bg-muted/30 transition-colors">
                  <TableCell className="h-10 px-3 align-middle">{item.name}</TableCell>
                  <TableCell className="h-10 px-3 align-middle">
                    <Badge variant="secondary" className="text-xs">
                      {shortType(item.type)}
                    </Badge>
                  </TableCell>
                  <TableCell className="h-10 px-3 align-middle">{item.location}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
