'use client';

import React, { useState } from 'react';
import {
  makeStyles,
  tokens,
  TabList,
  Tab,
  Text,
} from '@fluentui/react-components';
import {
  AlertRegular,
  OrganizationRegular,
  ServerRegular,
  ClipboardTaskRegular,
} from '@fluentui/react-icons';
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
  },
  dashboardPanel: {
    overflow: 'hidden',
    display: 'flex',
    flexDirection: 'column',
    backgroundColor: tokens.colorNeutralBackground3,
  },
});

type DashboardTab = 'alerts' | 'topology' | 'resources' | 'audit';

export function AppLayout() {
  const styles = useStyles();
  const [activeTab, setActiveTab] = useState<DashboardTab>('alerts');
  const [selectedSubscriptions, setSelectedSubscriptions] = useState<string[]>([]);

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
          />
        </div>
      </div>

      {/* Split-Pane Content */}
      <div className={styles.mainContent}>
        <PanelGroup
          direction="horizontal"
          autoSaveId="aap-main-layout"
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
            <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
              <TabList
                selectedValue={activeTab}
                onTabSelect={(_, data) => setActiveTab(data.value as DashboardTab)}
                style={{ paddingLeft: tokens.spacingHorizontalL }}
              >
                <Tab value="alerts" icon={<AlertRegular />}>Alerts</Tab>
                <Tab value="topology" icon={<OrganizationRegular />}>Topology</Tab>
                <Tab value="resources" icon={<ServerRegular />}>Resources</Tab>
                <Tab value="audit" icon={<ClipboardTaskRegular />}>Audit Log</Tab>
              </TabList>
              <div style={{ flex: 1, overflow: 'auto', padding: tokens.spacingHorizontalL }}>
                <DashboardPanel
                  activeTab={activeTab}
                  subscriptions={selectedSubscriptions}
                />
              </div>
            </div>
          </Panel>
        </PanelGroup>
      </div>
    </div>
  );
}
