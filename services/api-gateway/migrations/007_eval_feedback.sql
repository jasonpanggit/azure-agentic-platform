-- Migration 007: eval_feedback table for AIOps Quality Flywheel (Phase 63)
-- Stores operator approve/reject decisions as training signal.

CREATE TABLE IF NOT EXISTS eval_feedback (
    feedback_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id TEXT NOT NULL,
    action_type TEXT NOT NULL CHECK (action_type IN ('approve', 'reject', 'resolved', 'degraded')),
    operator_id TEXT,
    agent_response_summary TEXT,
    operator_decision TEXT,
    verification_outcome TEXT CHECK (verification_outcome IN ('RESOLVED', 'DEGRADED', 'UNKNOWN')),
    response_quality_score FLOAT CHECK (response_quality_score BETWEEN 0 AND 1),
    sop_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_eval_feedback_incident ON eval_feedback(incident_id);
CREATE INDEX IF NOT EXISTS idx_eval_feedback_sop ON eval_feedback(sop_id);
CREATE INDEX IF NOT EXISTS idx_eval_feedback_created ON eval_feedback(created_at DESC);
