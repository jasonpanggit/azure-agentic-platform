'use client';

import React, { useState } from 'react';
import {
  PanelGroup,
  Panel,
  PanelResizeHandle,
} from 'react-resizable-panels';
import { SubscriptionSelector } from './SubscriptionSelector';
import { ChatPanel } from './ChatPanel';
import { DashboardPanel } from './DashboardPanel';

export function AppLayout() {
  const [selectedSubscriptions, setSelectedSubscriptions] = useState<string[]>([]);
  const [selectedIncidentId, setSelectedIncidentId] = useState<string | undefined>();

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      {/* Top Bar */}
      <div className="flex items-center justify-between px-6 py-2 border-b bg-background shadow-sm z-10">
        <div className="flex items-center gap-4">
          <h1 className="text-xl font-semibold">Azure AIOps</h1>
        </div>
        <div className="flex items-center gap-6">
          <SubscriptionSelector
            selected={selectedSubscriptions}
            onChange={setSelectedSubscriptions}
            onLoad={setSelectedSubscriptions}
          />
        </div>
      </div>

      {/* Split-Pane Content */}
      <div className="flex-1 min-h-0 overflow-hidden">
        <PanelGroup
          direction="horizontal"
          autoSaveId="aap-main-layout"
          className="h-full"
        >
          <Panel
            defaultSize={35}
            minSize={25}
            className="relative overflow-hidden h-full bg-background"
          >
            <ChatPanel subscriptions={selectedSubscriptions} />
          </Panel>

          <PanelResizeHandle className="w-2 bg-transparent border-l border-border cursor-col-resize hover:border-primary transition-colors" />

          <Panel
            defaultSize={65}
            minSize={40}
            className="overflow-hidden flex flex-col bg-muted h-full"
          >
            <DashboardPanel
              subscriptions={selectedSubscriptions}
              selectedIncidentId={selectedIncidentId}
            />
          </Panel>
        </PanelGroup>
      </div>
    </div>
  );
}
