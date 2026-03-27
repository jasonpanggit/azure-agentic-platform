import { getGatewayToken } from "./auth";

export interface ChatRequestBody {
  message: string;
  incident_id?: string;
  thread_id?: string;
  user_id?: string;
}

export interface ChatResponseBody {
  thread_id: string;
  status: string;
}

export interface ApprovalRecord {
  id: string;
  action_id: string;
  thread_id: string;
  incident_id?: string;
  agent_name: string;
  status: string;
  risk_level: string;
  proposed_at: string;
  expires_at: string;
  decided_at?: string;
  decided_by?: string;
  proposal: Record<string, unknown>;
}

export class GatewayClient {
  constructor(
    private readonly baseUrl: string,
    private readonly apiGatewayClientId?: string,
  ) {}

  private async authHeaders(): Promise<Record<string, string>> {
    const token = await getGatewayToken(this.apiGatewayClientId);
    return {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    };
  }

  async chat(body: ChatRequestBody): Promise<ChatResponseBody> {
    const headers = await this.authHeaders();
    const response = await fetch(`${this.baseUrl}/api/v1/chat`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      throw new Error(`Chat failed: ${response.status} ${response.statusText}`);
    }
    return response.json() as Promise<ChatResponseBody>;
  }

  async getIncident(incidentId: string): Promise<Record<string, unknown>> {
    const headers = await this.authHeaders();
    const response = await fetch(
      `${this.baseUrl}/api/v1/incidents?limit=50`,
      { method: "GET", headers },
    );
    if (!response.ok) {
      throw new Error(`Incident lookup failed: ${response.status}`);
    }
    const results = (await response.json()) as Array<Record<string, unknown>>;
    const match = results.find((r) => r.incident_id === incidentId);
    if (!match) {
      throw new Error(`Incident ${incidentId} not found`);
    }
    return match;
  }

  async approveProposal(
    approvalId: string,
    threadId: string,
    decidedBy: string,
  ): Promise<void> {
    const headers = await this.authHeaders();
    const response = await fetch(
      `${this.baseUrl}/api/v1/approvals/${approvalId}/approve?thread_id=${encodeURIComponent(threadId)}`,
      {
        method: "POST",
        headers,
        body: JSON.stringify({ decided_by: decidedBy }),
      },
    );
    if (!response.ok) {
      throw new Error(`Approve failed: ${response.status}`);
    }
  }

  async rejectProposal(
    approvalId: string,
    threadId: string,
    decidedBy: string,
  ): Promise<void> {
    const headers = await this.authHeaders();
    const response = await fetch(
      `${this.baseUrl}/api/v1/approvals/${approvalId}/reject?thread_id=${encodeURIComponent(threadId)}`,
      {
        method: "POST",
        headers,
        body: JSON.stringify({ decided_by: decidedBy }),
      },
    );
    if (!response.ok) {
      throw new Error(`Reject failed: ${response.status}`);
    }
  }

  async listPendingApprovals(): Promise<ApprovalRecord[]> {
    const headers = await this.authHeaders();
    const response = await fetch(
      `${this.baseUrl}/api/v1/approvals?status=pending`,
      { method: "GET", headers },
    );
    if (!response.ok) {
      throw new Error(`List pending approvals failed: ${response.status}`);
    }
    return response.json() as Promise<ApprovalRecord[]>;
  }
}
