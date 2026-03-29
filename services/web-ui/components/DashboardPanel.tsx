'use client';

import React, { useState } from 'react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Bell, ClipboardList, Network, Server, Activity } from 'lucide-react';
import { AlertFeed } from './AlertFeed';
import { AlertFilters } from './AlertFilters';
import { AuditLogViewer } from './AuditLogViewer';
import { ObservabilityTab } from './ObservabilityTab';
import { ResourcesTab } from './ResourcesTab';
import { TopologyTab } from './TopologyTab';

interface FilterState {
  severity?: string;
  domain?: string;
  status?: string;
}

interface DashboardPanelProps {
  subscriptions: string[];
  selectedIncidentId?: string;
}

export function DashboardPanel({ subscriptions, selectedIncidentId }: DashboardPanelProps) {
  const [filters, setFilters] = useState<FilterState>({});

  return (
    <div className="flex flex-col h-full overflow-hidden bg-muted">
      <Tabs defaultValue="alerts" className="flex flex-col h-full">
        <div className="px-4 shadow-sm bg-background border-b border-border">
          <TabsList>
            <TabsTrigger value="alerts" className="gap-1.5">
              <Bell className="h-4 w-4" />
              Alerts
            </TabsTrigger>
            <TabsTrigger value="audit" className="gap-1.5">
              <ClipboardList className="h-4 w-4" />
              Audit
            </TabsTrigger>
            <TabsTrigger value="topology" className="gap-1.5">
              <Network className="h-4 w-4" />
              Topology
            </TabsTrigger>
            <TabsTrigger value="resources" className="gap-1.5">
              <Server className="h-4 w-4" />
              Resources
            </TabsTrigger>
            <TabsTrigger value="observability" className="gap-1.5">
              <Activity className="h-4 w-4" />
              Observability
            </TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="alerts" className="flex-1 overflow-auto p-4 mt-0">
          <div className="flex flex-col gap-2 h-full">
            <AlertFilters filters={filters} onChange={setFilters} />
            <AlertFeed subscriptions={subscriptions} filters={filters} />
          </div>
        </TabsContent>

        <TabsContent value="audit" className="flex-1 overflow-auto p-4 mt-0">
          <AuditLogViewer incidentId={selectedIncidentId} />
        </TabsContent>

        <TabsContent value="topology" className="flex-1 overflow-auto p-4 mt-0">
          <TopologyTab subscriptions={subscriptions} />
        </TabsContent>

        <TabsContent value="resources" className="flex-1 overflow-auto p-4 mt-0">
          <ResourcesTab subscriptions={subscriptions} />
        </TabsContent>

        <TabsContent value="observability" className="flex-1 overflow-auto p-4 mt-0">
          <ObservabilityTab subscriptions={subscriptions} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
