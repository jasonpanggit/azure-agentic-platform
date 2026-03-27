'use client';

// PLACEHOLDER: replaced by Plan 05-04 Task 5-04-08 with full HITL approval card.
// This stub satisfies the import from ChatPanel and defines the props interface.

import React from 'react';
import { Card, Text, Button } from '@fluentui/react-components';

interface ProposalCardProps {
  approval: {
    id: string;
    status: string;
    risk_level: string;
    expires_at: string;
    proposal: {
      description: string;
      target_resources: string[];
      estimated_impact: string;
      reversibility: string;
    };
  };
  onApprove: () => void;
  onReject: () => void;
}

export function ProposalCard({ approval, onApprove, onReject }: ProposalCardProps) {
  return (
    <Card style={{ margin: '8px 0', border: '2px solid orange' }}>
      <Text weight="semibold">Approval Required: {approval.proposal.description}</Text>
      <Text size={200}>Risk: {approval.risk_level} | Impact: {approval.proposal.estimated_impact}</Text>
      <div style={{ display: 'flex', gap: '8px', marginTop: '8px' }}>
        <Button appearance="primary" onClick={onApprove}>Approve</Button>
        <Button appearance="secondary" onClick={onReject}>Reject</Button>
      </div>
    </Card>
  );
}
