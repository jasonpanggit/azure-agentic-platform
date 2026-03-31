'use client';

import React, { useState, useEffect } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';

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
  const [timeRemaining, setTimeRemaining] = useState('');
  const isPending = approval.status === 'pending';

  useEffect(() => {
    if (!isPending) return;
    const updateTimer = () => {
      const expires = new Date(approval.expires_at).getTime();
      const now = Date.now();
      const diff = expires - now;
      if (diff <= 0) { setTimeRemaining('Expired'); return; }
      const minutes = Math.floor(diff / 60000);
      const seconds = Math.floor((diff % 60000) / 1000);
      setTimeRemaining(`${minutes}:${seconds.toString().padStart(2, '0')}`);
    };
    updateTimer();
    const interval = setInterval(updateTimer, 1000);
    return () => clearInterval(interval);
  }, [isPending, approval.expires_at]);

  return (
    <Card
      className="max-w-[90%] self-start p-4 mb-2"
      style={{
        border: '1px solid var(--border)',
        borderLeft: `4px solid ${approval.risk_level === 'critical' ? 'var(--accent-red)' : 'var(--accent-orange)'}`,
        background: 'var(--bg-subtle)',
        borderRadius: '8px',
      }}
    >
      <CardContent className="p-0">
        <div className="flex items-center gap-2 mb-2">
          <Badge variant={approval.risk_level === 'critical' ? 'destructive' : 'outline'}>
            {approval.risk_level.toUpperCase()}
          </Badge>
          <span className="font-semibold text-sm">{approval.proposal.description}</span>
          {!isPending && (
            <Badge variant={approval.status === 'approved' || approval.status === 'executed' ? 'default' : 'destructive'}>
              {approval.status === 'aborted' ? `Aborted — ${approval.abort_reason || 'stale_approval'}` : approval.status.charAt(0).toUpperCase() + approval.status.slice(1)}
            </Badge>
          )}
        </div>
        <div className="flex flex-col gap-1 mb-3">
          <p className="text-sm"><strong>Target:</strong> <span className="font-mono text-[13px] text-muted-foreground">{approval.proposal.target_resources.join(', ')}</span></p>
          <p className="text-sm"><strong>Impact:</strong> {approval.proposal.estimated_impact}</p>
          <p className="text-sm"><strong>Reversibility:</strong> {approval.proposal.reversibility}</p>
        </div>
        {isPending && (
          <>
            <p className={`text-sm mt-2 ${timeRemaining === 'Expired' ? 'text-destructive' : 'text-muted-foreground'}`}>
              {timeRemaining === 'Expired' ? 'Expired' : `This approval expires in ${timeRemaining}`}
            </p>
            <div className="flex gap-2 mt-2">
              <Dialog>
                <DialogTrigger asChild><Button style={{ background: 'var(--accent-green)', color: '#FFFFFF', border: 'none' }}>Approve Action</Button></DialogTrigger>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>Approve Action</DialogTitle>
                    <DialogDescription>
                      This action is rated <strong>{approval.risk_level}</strong>. It will {approval.proposal.description.toLowerCase()} on {approval.proposal.target_resources[0]}. Estimated impact: {approval.proposal.estimated_impact}. Proceed?
                    </DialogDescription>
                  </DialogHeader>
                  <DialogFooter>
                    <DialogTrigger asChild><Button variant="secondary">Cancel</Button></DialogTrigger>
                    <Button onClick={onApprove} style={{ background: 'var(--accent-green)', color: '#FFFFFF', border: 'none' }}>Confirm Approval</Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>
              <Dialog>
                <DialogTrigger asChild><Button style={{ background: 'var(--accent-red)', color: '#FFFFFF', border: 'none' }}>Reject Action</Button></DialogTrigger>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>Reject Action</DialogTitle>
                    <DialogDescription>Are you sure you want to reject this remediation? The agent will not proceed with this action.</DialogDescription>
                  </DialogHeader>
                  <DialogFooter>
                    <DialogTrigger asChild><Button variant="secondary">Cancel</Button></DialogTrigger>
                    <Button onClick={onReject} style={{ background: 'var(--accent-red)', color: '#FFFFFF', border: 'none' }}>Confirm Rejection</Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>
            </div>
          </>
        )}
        {!isPending && approval.decided_by && (
          <p className="text-sm text-muted-foreground">{approval.status === 'approved' ? 'Approved' : 'Rejected'} by {approval.decided_by} at {approval.decided_at}</p>
        )}
        {approval.status === 'expired' && (
          <p className="text-sm text-muted-foreground">This approval has expired and can no longer be acted upon.</p>
        )}
        {approval.status === 'aborted' && (
          <p className="text-sm text-muted-foreground">Action aborted: the target resource changed since this action was proposed. A new assessment is needed.</p>
        )}
      </CardContent>
    </Card>
  );
}
