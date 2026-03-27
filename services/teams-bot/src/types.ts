export type CardType = "alert" | "approval" | "outcome" | "reminder";

export interface NotifyRequest {
  card_type: CardType;
  channel_id: string;
  payload: AlertPayload | ApprovalPayload | OutcomePayload | ReminderPayload;
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
