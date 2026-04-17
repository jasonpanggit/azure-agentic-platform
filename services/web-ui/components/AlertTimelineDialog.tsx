'use client'

import { useState } from 'react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { AlertTimeline } from './AlertTimeline'
import { GitBranch } from 'lucide-react'

interface AlertTimelineDialogProps {
  incidentId: string
  incidentTitle?: string
  /** Optional render prop — if not supplied, renders a default "View Timeline" button */
  trigger?: (open: () => void) => React.ReactNode
}

export function AlertTimelineDialog({
  incidentId,
  incidentTitle,
  trigger,
}: AlertTimelineDialogProps) {
  const [open, setOpen] = useState(false)

  const openDialog = () => setOpen(true)

  return (
    <>
      {trigger ? (
        trigger(openDialog)
      ) : (
        <button
          onClick={openDialog}
          className="text-xs px-2 py-1 rounded cursor-pointer transition-colors flex items-center gap-1"
          style={{
            background: 'color-mix(in srgb, var(--accent-blue) 12%, transparent)',
            color: 'var(--accent-blue)',
            border: '1px solid color-mix(in srgb, var(--accent-blue) 30%, transparent)',
          }}
          title="View alert correlation timeline"
        >
          <GitBranch className="w-3 h-3" />
          Timeline
        </button>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent
          className="max-w-2xl max-h-[80vh] overflow-y-auto"
          style={{ background: 'var(--bg-canvas)' }}
        >
          <DialogHeader>
            <DialogTitle
              className="flex items-center gap-2 text-base"
              style={{ color: 'var(--text-primary)' }}
            >
              <GitBranch className="w-4 h-4" style={{ color: 'var(--accent-blue)' }} />
              {incidentTitle ? `Timeline — ${incidentTitle}` : `Timeline — ${incidentId}`}
            </DialogTitle>
          </DialogHeader>

          <AlertTimeline incidentId={incidentId} />
        </DialogContent>
      </Dialog>
    </>
  )
}
