'use client';

import React, { useState } from 'react';
import {
  makeStyles,
  tokens,
  Text,
} from '@fluentui/react-components';
import {
  PanelGroup,
  Panel,
  PanelResizeHandle,
} from 'react-resizable-panels';
import { SubscriptionSelector } from './SubscriptionSelector';
import { ChatPanel } from './ChatPanel';
import { DashboardPanel } from './DashboardPanel';

const useStyles = makeStyles({
  root: {
    display: 'flex',
    flexDirection: 'column',
    height: '100vh',
    overflow: 'hidden',
  },
  topBar: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingLeft: tokens.spacingHorizontalXXL,
    paddingRight: tokens.spacingHorizontalXXL,
    paddingTop: tokens.spacingVerticalS,
    paddingBottom: tokens.spacingVerticalS,
    borderBottom: `1px solid ${tokens.colorNeutralStroke1}`,
    backgroundColor: tokens.colorNeutralBackground1,
    boxShadow: tokens.shadow4,
    zIndex: 1,
  },
  title: {
    display: 'flex',
    alignItems: 'center',
    gap: tokens.spacingHorizontalM,
  },
  topBarRight: {
    display: 'flex',
    alignItems: 'center',
    gap: tokens.spacingHorizontalL,
  },
  mainContent: {
    flex: 1,
    minHeight: 0,
    overflow: 'hidden',
  },
  resizeHandle: {
    width: '8px',
    backgroundColor: 'transparent',
    borderLeft: `1px solid ${tokens.colorNeutralStroke1}`,
    cursor: 'col-resize',
  },
  chatPanel: {
    overflow: 'hidden',
    display: 'flex',
    flexDirection: 'column',
    backgroundColor: tokens.colorNeutralBackground1,
    minHeight: 0,
  },
  dashboardPanel: {
    overflow: 'hidden',
    display: 'flex',
    flexDirection: 'column',
    backgroundColor: tokens.colorNeutralBackground3,
    height: '100%',
  },
});

export function AppLayout() {
  const styles = useStyles();
  const [selectedSubscriptions, setSelectedSubscriptions] = useState<string[]>([]);
  const [selectedIncidentId, setSelectedIncidentId] = useState<string | undefined>();

  return (
    <div className={styles.root}>
      {/* Top Bar */}
      <div className={styles.topBar}>
        <div className={styles.title}>
          <Text as="h1" weight="semibold" size={500}>
            Azure AIOps
          </Text>
        </div>
        <div className={styles.topBarRight}>
          <SubscriptionSelector
            selected={selectedSubscriptions}
            onChange={setSelectedSubscriptions}
            onLoad={setSelectedSubscriptions}
          />
        </div>
      </div>

      {/* Split-Pane Content */}
      <div className={styles.mainContent}>
        <PanelGroup
          direction="horizontal"
          autoSaveId="aap-main-layout"
          style={{ height: '100%' }}
        >
          <Panel
            defaultSize={35}
            minSize={25}
            className={styles.chatPanel}
          >
            <ChatPanel subscriptions={selectedSubscriptions} />
          </Panel>

          <PanelResizeHandle className={styles.resizeHandle} />

          <Panel
            defaultSize={65}
            minSize={40}
            className={styles.dashboardPanel}
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
