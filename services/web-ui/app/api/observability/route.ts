import { NextResponse } from "next/server";
import { DefaultAzureCredential } from "@azure/identity";
import { LogsQueryClient, LogsQueryResultStatus } from "@azure/monitor-query";
import { CosmosClient } from "@azure/cosmos";

const WORKSPACE_ID = process.env.LOG_ANALYTICS_WORKSPACE_ID || "";
const COSMOS_ENDPOINT = process.env.COSMOS_ENDPOINT || "";
const COSMOS_DATABASE = process.env.COSMOS_DATABASE_NAME || "aap";

interface AgentLatencyRow {
  agent: string;
  p50: number;
  p95: number;
}

interface PipelineLagData {
  alertToIncidentMs: number;
  incidentToTriageMs: number;
  totalE2EMs: number;
}

interface ApprovalQueueData {
  pending: number;
  oldestPendingMinutes: number | null;
}

interface ActiveError {
  timestamp: string;
  agent: string;
  error: string;
  detail: string;
}

interface ObservabilityResponse {
  agentLatency: AgentLatencyRow[];
  pipelineLag: PipelineLagData;
  approvalQueue: ApprovalQueueData;
  activeErrors: ActiveError[];
  lastUpdated: string;
}

const TIME_RANGE_MAP: Record<string, string> = {
  "1h": "PT1H",
  "6h": "PT6H",
  "24h": "P1D",
  "7d": "P7D",
};

export async function GET(request: Request): Promise<NextResponse> {
  const { searchParams } = new URL(request.url);
  const timeRange = searchParams.get("timeRange") || "1h";
  const isoDuration = TIME_RANGE_MAP[timeRange] || "PT1H";

  if (!WORKSPACE_ID) {
    return NextResponse.json(
      { error: "LOG_ANALYTICS_WORKSPACE_ID not configured" },
      { status: 503 }
    );
  }

  try {
    const credential = new DefaultAzureCredential();
    const logsClient = new LogsQueryClient(credential);

    // Execute all queries in parallel
    const [latencyResult, lagResult, errorsResult, approvalQueue] =
      await Promise.all([
        queryAgentLatency(logsClient, isoDuration),
        queryPipelineLag(logsClient, isoDuration),
        queryActiveErrors(logsClient, isoDuration),
        queryApprovalQueue(),
      ]);

    const response: ObservabilityResponse = {
      agentLatency: latencyResult,
      pipelineLag: lagResult,
      approvalQueue: approvalQueue,
      activeErrors: errorsResult,
      lastUpdated: new Date().toISOString(),
    };

    return NextResponse.json(response);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json(
      { error: `Failed to fetch observability data: ${message}` },
      { status: 500 }
    );
  }
}

async function queryAgentLatency(
  client: LogsQueryClient,
  duration: string
): Promise<AgentLatencyRow[]> {
  const kql = `AppDependencies
| where AppRoleName startswith "agent-"
| summarize P50=percentile(DurationMs, 50), P95=percentile(DurationMs, 95) by AppRoleName
| project Agent=replace_string(AppRoleName, "agent-", ""), P50=round(P50, 0), P95=round(P95, 0)
| order by Agent asc`;

  const result = await client.queryWorkspace(WORKSPACE_ID, kql, {
    duration,
  });

  if (result.status !== LogsQueryResultStatus.Success || !result.tables?.[0]) {
    return [];
  }
  return result.tables[0].rows.map((row: unknown[]) => ({
    agent: String(row[0]),
    p50: Number(row[1]),
    p95: Number(row[2]),
  }));
}

async function queryPipelineLag(
  client: LogsQueryClient,
  duration: string
): Promise<PipelineLagData> {
  const kql = `AppDependencies
| where AppRoleName == "api-gateway" and Name == "POST /api/v1/incidents"
| summarize AvgDurationMs=avg(DurationMs)
| project AlertToIncidentMs=round(AvgDurationMs, 0)`;

  const result = await client.queryWorkspace(WORKSPACE_ID, kql, {
    duration,
  });

  const alertToIncident =
    result.status === LogsQueryResultStatus.Success &&
    result.tables?.[0]?.rows?.[0]
      ? Number(result.tables[0].rows[0][0])
      : 0;

  return {
    alertToIncidentMs: alertToIncident,
    incidentToTriageMs: 0,
    totalE2EMs: alertToIncident,
  };
}

async function queryActiveErrors(
  client: LogsQueryClient,
  duration: string
): Promise<ActiveError[]> {
  const kql = `AppExceptions
| where AppRoleName startswith "agent-" or AppRoleName == "api-gateway"
| order by TimeGenerated desc
| take 20
| project TimeGenerated, AppRoleName, ExceptionType, OuterMessage`;

  const result = await client.queryWorkspace(WORKSPACE_ID, kql, {
    duration,
  });

  if (result.status !== LogsQueryResultStatus.Success || !result.tables?.[0]) {
    return [];
  }
  return result.tables[0].rows.map((row: unknown[]) => ({
    timestamp: String(row[0]),
    agent: String(row[1]).replace("agent-", ""),
    error: String(row[2]),
    detail: String(row[3]),
  }));
}

async function queryApprovalQueue(): Promise<ApprovalQueueData> {
  if (!COSMOS_ENDPOINT) {
    return { pending: 0, oldestPendingMinutes: null };
  }
  try {
    const credential = new DefaultAzureCredential();
    const cosmos = new CosmosClient({ endpoint: COSMOS_ENDPOINT, aadCredentials: credential });
    const container = cosmos
      .database(COSMOS_DATABASE)
      .container("approvals");

    const { resources } = await container.items
      .query({
        query:
          "SELECT c.proposed_at FROM c WHERE c.status = 'pending' ORDER BY c.proposed_at ASC",
        parameters: [],
      })
      .fetchAll();

    const pending = resources.length;
    let oldestPendingMinutes: number | null = null;
    if (pending > 0 && resources[0].proposed_at) {
      const oldest = new Date(resources[0].proposed_at);
      oldestPendingMinutes = Math.round(
        (Date.now() - oldest.getTime()) / 60000
      );
    }
    return { pending, oldestPendingMinutes };
  } catch {
    return { pending: 0, oldestPendingMinutes: null };
  }
}
