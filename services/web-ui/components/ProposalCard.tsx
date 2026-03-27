'use client';

import React, { useState, useEffect } from 'react';
import {
  Card,
  Text,
  Button,
  Badge,
  makeStyles,
  tokens,
  Dialog,
  DialogTrigger,
  DialogSurface,
  DialogTitle,
  DialogBody,
  DialogActions,
  DialogContent,
} from '@fluentui/react-components';

const useStyles = makeStyles({
  root: {
    maxWidth: '90%',
    alignSelf: 'flex-start',
    padding: tokens.spacingHorizontalM,
    marginBottom: tokens.spacingVerticalS,
    border: `1px solid ${tokens.colorPaletteRedBorderActive}`,
    boxShadow: tokens.shadow8,
    borderRadius: tokens.borderRadiusLarge,
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: tokens.spacingHorizontalS,
    marginBottom: tokens.spacingVerticalS,
  },
  details: {
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalXS,
    marginBottom: tokens.spacingVerticalM,
  },
  actions: {
    display: 'flex',
    gap: tokens.spacingHorizontalS,
  },
  timer: {
    marginTop: tokens.spacingVerticalS,
  },
  monospace: {
    fontFamily: tokens.fontFamilyMonospace,
    fontSize: '12px',
  },
});

interface ProposalCardProps {
  approval: {
    id: string;
    status: string;
    risk_level: string;
    expires_at: string;
    decided_by?: string;
    decided_at?: string;
    abort_reason?: string;
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
  const styles = useStyles();
  const [timeRemaining, setTimeRemaining] = useState('');
  const isPending = approval.status === 'pending';

  useEffect(() => {
    if (!isPending) return;

    const updateTimer = () => {
      const expires = new Date(approval.expires_at).getTime();
      const now = Date.now();
      const diff = expires - now;

      if (diff <= 0) {
        setTimeRemaining('Expired');
        return;
      }
      const minutes = Math.floor(diff / 60000);
      const seconds = Math.floor((diff % 60000) / 1000);
      setTimeRemaining(`${minutes}:${seconds.toString().padStart(2, '0')}`);
    };

    updateTimer();
    const interval = setInterval(updateTimer, 1000);
    return () => clearInterval(interval);
  }, [isPending, approval.expires_at]);

  const riskBadgeColor = approval.risk_level === 'critical' ? 'danger' : 'important';

  const statusBadges: Record<string, { color: 'success' | 'danger' | 'warning' | 'important'; label: string }> = {
    approved: { color: 'success', label: 'Approved' },
    rejected: { color: 'danger', label: 'Rejected' },
    expired: { color: 'warning', label: 'Expired' },
    aborted: { color: 'danger', label: `Aborted — ${approval.abort_reason || 'stale_approval'}` },
    executed: { color: 'success', label: 'Executed' },
  };

  return (
    <Card className={styles.root} size="small">
      <div className={styles.header}>
        <Badge color={riskBadgeColor} appearance="filled">
          {approval.risk_level.toUpperCase()}
        </Badge>
        <Text weight="semibold">{approval.proposal.description}</Text>
        {!isPending && statusBadges[approval.status] && (
          <Badge color={statusBadges[approval.status].color} appearance="filled">
            {statusBadges[approval.status].label}
          </Badge>
        )}
      </div>

      <div className={styles.details}>
        <Text size={200}>
          <strong>Target:</strong>{' '}
          <span className={styles.monospace}>
            {approval.proposal.target_resources.join(', ')}
          </span>
        </Text>
        <Text size={200}>
          <strong>Impact:</strong> {approval.proposal.estimated_impact}
        </Text>
        <Text size={200}>
          <strong>Reversibility:</strong> {approval.proposal.reversibility}
        </Text>
      </div>

      {isPending && (
        <>
          <div className={styles.timer}>
            <Text size={200}>
              This approval expires in {timeRemaining}
            </Text>
          </div>
          <div className={styles.actions}>
            <Dialog>
              <DialogTrigger disableButtonEnhancement>
                <Button appearance="primary">Approve Action</Button>
              </DialogTrigger>
              <DialogSurface>
                <DialogBody>
                  <DialogTitle>Approve Action</DialogTitle>
                  <DialogContent>
                    This action is rated <strong>{approval.risk_level}</strong>. It will{' '}
                    {approval.proposal.description.toLowerCase()} on{' '}
                    {approval.proposal.target_resources[0]}. Estimated impact:{' '}
                    {approval.proposal.estimated_impact}. Proceed?
                  </DialogContent>
                  <DialogActions>
                    <DialogTrigger disableButtonEnhancement>
                      <Button appearance="secondary">Cancel</Button>
                    </DialogTrigger>
                    <Button appearance="primary" onClick={onApprove}>
                      Confirm Approval
                    </Button>
                  </DialogActions>
                </DialogBody>
              </DialogSurface>
            </Dialog>

            <Dialog>
              <DialogTrigger disableButtonEnhancement>
                <Button appearance="secondary" style={{ color: tokens.colorPaletteRedForeground1 }}>
                  Reject Action
                </Button>
              </DialogTrigger>
              <DialogSurface>
                <DialogBody>
                  <DialogTitle>Reject Action</DialogTitle>
                  <DialogContent>
                    Are you sure you want to reject this remediation? The agent will not proceed with this action.
                  </DialogContent>
                  <DialogActions>
                    <DialogTrigger disableButtonEnhancement>
                      <Button appearance="secondary">Cancel</Button>
                    </DialogTrigger>
                    <Button
                      appearance="primary"
                      onClick={onReject}
                      style={{ backgroundColor: tokens.colorPaletteRedBackground3 }}
                    >
                      Confirm Rejection
                    </Button>
                  </DialogActions>
                </DialogBody>
              </DialogSurface>
            </Dialog>
          </div>
        </>
      )}

      {!isPending && approval.decided_by && (
        <Text size={200}>
          {approval.status === 'approved' ? 'Approved' : 'Rejected'} by {approval.decided_by} at{' '}
          {approval.decided_at}
        </Text>
      )}

      {approval.status === 'expired' && (
        <Text size={200}>
          This approval has expired and can no longer be acted upon.
        </Text>
      )}

      {approval.status === 'aborted' && (
        <Text size={200}>
          Action aborted: the target resource changed since this action was proposed. A new assessment is needed.
        </Text>
      )}
    </Card>
  );
}
