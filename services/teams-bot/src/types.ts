export type CardType =
  | "alert"
  | "approval"
  | "outcome"
  | "reminder"
  | "sop_notification"
  | "sop_escalation"
  | "sop_summary"
  | "war_room_created"
  | "war_room_annotation";

export interface NotifyRequest {
  card_type: CardType;
  channel_id: string;
  payload:
    | AlertPayload
    | ApprovalPayload
    | OutcomePayload
    | ReminderPayload
    | SopNotificationPayload
    | SopEscalationPayload
    | SopSummaryPayload
    | WarRoomCreatedPayload
    | WarRoomAnnotationPayload;
}

export interface NotifyResponse {
  ok: boolean;
  message_id?: string;
  error?: string;
}

export interface AlertPayload {
  incident_id: string;
  alert_title: string;
  resource_name: string;
  severity: "Sev0" | "Sev1" | "Sev2" | "Sev3";
  subscription_name: string;
  domain: string;
  timestamp: string;
}

export interface ApprovalPayload {
  approval_id: string;
  thread_id: string;
  proposal: {
    description: string;
    target_resources: string[];
    estimated_impact: string;
    reversibility: string;
  };
  risk_level: "critical" | "high";
  expires_at: string;
}

export interface OutcomePayload {
  incident_id: string;
  approval_id: string;
  action_description: string;
  outcome_status: "Succeeded" | "Failed" | "Aborted";
  duration_seconds: number;
  resulting_resource_state: string;
  approver_upn: string;
  executed_at: string;
}

export interface ReminderPayload {
  approval_id: string;
  thread_id: string;
  original_action_description: string;
  target_resources: string[];
  risk_level: "critical" | "high";
  created_at: string;
  expires_at: string;
}

export interface SopNotificationPayload {
  incident_id: string;
  resource_name: string;
  message: string;
  severity: "info" | "warning" | "critical";
  sop_step: string;
}

export interface SopEscalationPayload {
  incident_id: string;
  resource_name: string;
  message: string;
  sop_step: string;
  context: string;
}

export interface SopSummaryPayload {
  incident_id: string;
  resource_name: string;
  sop_title: string;
  steps_run: number;
  steps_skipped: number;
  outcome: "resolved" | "escalated" | "pending_approval" | "failed";
}

/** Payload for war_room_created card — sent when an operator joins a P0 incident war room */
export interface WarRoomCreatedPayload {
  incident_id: string;
  incident_title?: string;
  severity: string;
  resource_name?: string;
  participants: Array<{
    operator_id: string;
    display_name: string;
    role: string;
  }>;
  /** Deep link to the incident in the Web UI */
  incident_url?: string;
}

/** Payload for war_room_annotation card — syncs a new annotation to the Teams thread */
export interface WarRoomAnnotationPayload {
  incident_id: string;
  incident_title?: string;
  annotation: {
    id: string;
    operator_id: string;
    display_name: string;
    content: string;
    created_at: string;
    trace_event_id: string | null;
  };
}
