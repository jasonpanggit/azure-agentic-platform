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
      {/* Top Bar — stronger visual identity with primary accent */}
      <div className="flex items-center justify-between px-6 py-2.5 border-b bg-card shadow-sm z-10">
        <div className="flex items-center gap-3">
          {/* Azure blue accent dot */}
          <span className="h-2 w-2 rounded-full bg-primary shrink-0" />
          <h1 className="text-lg font-semibold tracking-tight">Azure AIOps</h1>
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
          {/* Chat panel — slightly blue-tinted so it reads as distinct from dashboard */}
          <Panel
            defaultSize={35}
            minSize={25}
            className="relative overflow-hidden h-full bg-secondary"
          >
            <ChatPanel subscriptions={selectedSubscriptions} />
          </Panel>

          <PanelResizeHandle className="w-1.5 bg-border/60 cursor-col-resize hover:bg-primary/40 transition-colors" />

          {/* Dashboard panel */}
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
