# AIOps Platform — Pitfalls & Prevention

> Last updated: 2026-03-25
> Stack: Microsoft Agent Framework (Python RC) · Foundry Hosted Agents (Preview) · Azure MCP Server (GA) · Custom Arc MCP Server · Fabric Eventhouse + Activator · Next.js + Fluent UI 2 · Teams Bot · Cosmos DB + PostgreSQL + Fabric OneLake · Azure Container Apps · Terraform (azurerm + azapi) · Playwright E2E

---

## 1. Agent Framework (Release Candidate)

### Breaking Changes Between RC Versions
- ⚠️ **Risk**: RC releases ship non-semver-compatible API changes (tool signatures, session contracts, agent lifecycle hooks). A silent upgrade can break all registered tools or corrupt in-flight conversations.
- 🛡️ **Prevention**: Pin the exact RC version in `requirements.txt` (`==` not `~=`). Lock the Docker base image digest. Run the full Playwright E2E suite before promoting any version bump. Maintain a `CHANGELOG-diff.md` tracking every RC upgrade.
- 📍 **Phase**: Dependency management — enforce at project setup and every Sprint 0.

### Context Overflow on Long Remediation Chains
- ⚠️ **Risk**: Multi-step AIOps workflows (diagnose → plan → approve → remediate → verify) accumulate context across agent handoffs. Token window exhaustion causes silent truncation or outright failures mid-remediation.
- 🛡️ **Prevention**: Implement a `ContextBudgetMiddleware` that tracks consumed tokens per session and triggers a summarization pass at 60% utilization. Store long tool outputs (KQL results, log dumps) in Cosmos DB and inject references, not raw content, into agent context.
- 📍 **Phase**: Agent architecture — design before any multi-step workflow is built.

### Token Cost Loops
- ⚠️ **Risk**: An agent that retries on tool failure, or calls a Monitor query that returns an ambiguous result, can spin indefinitely — burning tokens and accruing cost invisibly until a billing alert fires.
- 🛡️ **Prevention**: Enforce a hard `max_iterations` cap per agent session (recommend ≤ 10). Add a cost accumulator per session stored in Cosmos; abort and alert when it crosses a configurable threshold. Never allow a retry loop without exponential backoff and a ceiling.
- 📍 **Phase**: Agent runtime — required before any production workload.

### Agent-to-Agent (A2A) Message Ordering
- ⚠️ **Risk**: The RC A2A protocol does not guarantee delivery order across asynchronous handoffs. A "verify" agent can receive results before the "remediate" agent has committed its action, producing false-positive success signals.
- 🛡️ **Prevention**: Use monotonic sequence numbers on every A2A message. The receiving agent must validate sequence continuity before acting. Use Cosmos DB optimistic concurrency (ETag) on the shared session document to serialize cross-agent state updates.
- 📍 **Phase**: Agent orchestration design — establish the contract before building any multi-agent flow.

---

## 2. Foundry Hosted Agents (Preview)

### Cold Start Latency
- ⚠️ **Risk**: Preview-tier Foundry agents have no guaranteed warm pool. First invocation (or after idle) can take 15–45 seconds, which breaks synchronous UI flows and SSE streams that expect sub-5s first token.
- 🛡️ **Prevention**: Issue a no-op ping call on container app startup (warmup probe). For user-facing flows, show a "Connecting agent…" skeleton state in the UI and extend the SSE keep-alive ping interval to match the cold-start window.
- 📍 **Phase**: Infrastructure + UX — design warmup strategy before user-facing launch.

### No Private Networking (Preview Limitation)
- ⚠️ **Risk**: Foundry Hosted Agents in Preview cannot be injected into a VNet. All agent-to-backend traffic traverses public endpoints, which violates most enterprise network security baselines and can expose internal API surfaces.
- 🛡️ **Prevention**: Front all internal service calls through an APIM instance with IP allowlist + managed identity auth. Document this as a known gap; create a Terraform flag to swap in private endpoint configs when GA ships. Never route sensitive payloads (credentials, raw log data) through Foundry agents until private networking is available.
- 📍 **Phase**: Security design — must be a signed-off risk acceptance before Preview usage in production.

### Container Image Size
- ⚠️ **Risk**: Python agent images with ML/data dependencies bloat past 4–6 GB, causing slow deployments, high registry egress costs, and timeouts during container pull on first deploy.
- 🛡️ **Prevention**: Use multi-stage Docker builds. Keep the runtime stage to Python slim + only the agent framework + tool stubs. Push heavy dependencies (pandas, torch) to a separate data-processing container invoked via tool call, not bundled into the agent image.
- 📍 **Phase**: CI/CD pipeline — enforce image size gate (< 1.5 GB) before merge.

---

## 3. Azure MCP Server

### 100-Second Timeout on Long Monitor Queries
- ⚠️ **Risk**: Azure Monitor log queries over large time ranges (> 24h, high-cardinality workspaces) routinely exceed the MCP server's hard 100s HTTP timeout. The agent receives a timeout error and either retries (cost loop) or returns an empty/partial result silently.
- 🛡️ **Prevention**: Wrap all Monitor tool calls with time-range splitting — never query more than 4h in a single call; orchestrate multi-window queries in the agent. Cache results in Fabric Eventhouse with a TTL. Expose a `query_status` tool so the agent can poll async query jobs rather than blocking.
- 📍 **Phase**: MCP tool design — required before any log-analysis agent is built.

### Arc Gap (No Arc Support in GA MCP Server)
- ⚠️ **Risk**: The GA Azure MCP Server has no awareness of Arc-enabled resources. Agents querying hybrid/on-prem resources via the standard MCP server will silently miss them, producing incomplete remediation plans.
- 🛡️ **Prevention**: Route all Arc resource queries exclusively through the custom Arc MCP Server. Register both servers in the agent's tool manifest with explicit namespace prefixes (`azure_*` vs `arc_*`). Add an integration test that asserts Arc resources appear in the combined tool response.
- 📍 **Phase**: Tool registration — enforce namespace separation from day one.

### Elicitation Blocking Automation
- ⚠️ **Risk**: The MCP spec's elicitation (interactive clarification) mechanism will pause an automated agent waiting for human input indefinitely. In an AIOps pipeline, this silently stalls remediation with no timeout or alert.
- 🛡️ **Prevention**: Disable elicitation for all automated/non-human-in-the-loop agent flows at the MCP client config level. Set a `elicitation_timeout_seconds: 0` policy and route any ambiguous cases to a `needs_human_review` queue instead of blocking the pipeline.
- 📍 **Phase**: Agent runtime config — set policy before any automated remediation flow is deployed.

---

## 4. Fabric Activator

### No Direct HTTP Calls
- ⚠️ **Risk**: Activator rules cannot invoke HTTP endpoints natively. Teams/devs who expect Activator to directly trigger an AIOps agent or webhook will discover this gap at integration time, causing rework.
- 🛡️ **Prevention**: Design all Activator-to-agent paths through either Power Automate (for low-frequency, approval-gated actions) or a Fabric User Data Function (for code-controlled, high-frequency actions). Document this as a hard architectural constraint in the ADR. Never scope Activator to "call agent API directly."
- 📍 **Phase**: Architecture — decide Power Automate vs UDF per use case before building any alert-to-action flow.

### KQL Ingestion Delay (~30s Floor)
- ⚠️ **Risk**: Fabric Eventhouse has a ~30-second floor on streaming ingestion latency. Activator rules built on "real-time" data will actually act on data that is at minimum 30 seconds stale. For fast-moving incidents (CPU spike, OOM kill), this window means the alert may fire after the condition has already self-resolved.
- 🛡️ **Prevention**: Build Activator rules with hysteresis — require the condition to persist across two consecutive evaluation windows before triggering. Document the 30s floor in runbooks. For sub-30s detection, use Azure Monitor alerts (not Activator) as the primary trigger.
- 📍 **Phase**: Alert design — set expectations before building detection rules.

### Trigger Storm on Alert Floods
- ⚠️ **Risk**: A misconfigured KQL rule (e.g., alert on every row rather than aggregated threshold) combined with a high-cardinality event stream can produce thousands of Activator triggers per minute, flooding Power Automate / UDF queues and potentially running up costs.
- 🛡️ **Prevention**: All Activator rules must use aggregation windows (minimum 1-minute tumbling window) and include a deduplication key. Implement a per-alert-type rate limiter in the UDF/Power Automate handler. Set Activator action budget limits in preview settings. Test rules against a synthetic high-volume stream before production.
- 📍 **Phase**: Alert rule review — mandatory gate before any rule goes to production.

---

## 5. Dual SSE Streaming

### Azure Container Apps 240s Request Timeout
- ⚠️ **Risk**: ACA enforces a hard 240-second request timeout. Long-running agent sessions (complex diagnosis + multi-step remediation) will have their SSE connection hard-cut at 240s, leaving the client in an unknown state with no error event.
- 🛡️ **Prevention**: Implement SSE reconnection with a `Last-Event-ID` cursor. Break long agent sessions into phases; each phase is a separate SSE connection. Send a `heartbeat` event every 20s to keep the connection alive and allow the client to detect drops. Configure ACA ingress `requestTimeout` to the maximum (currently 240s) and design phases to complete within 180s with buffer.
- 📍 **Phase**: Infrastructure + streaming architecture — design reconnect protocol before any streaming UI is built.

### Fluent UI SSR/Client Boundary Issues
- ⚠️ **Risk**: Fluent UI 2 components that use `useId`, `useSSRContext`, or theme tokens hydrate differently between server and client in Next.js App Router, causing hydration mismatches that break SSE event rendering and produce console errors in production.
- 🛡️ **Prevention**: Wrap all Fluent UI stream-rendering components in `'use client'` and lazy-load them with `next/dynamic` (`ssr: false`). Do not render live SSE event content in RSC. Keep the SSE consumer entirely client-side.
- 📍 **Phase**: Frontend architecture — establish the RSC/client boundary rule before any streaming component is scaffolded.

### Trace Event Ordering During Agent Handoffs
- ⚠️ **Risk**: When one agent hands off to another (e.g., diagnostic → remediation), SSE events from both agents can arrive out of order at the client because they originate from different async tasks on potentially different container instances.
- 🛡️ **Prevention**: Stamp every SSE event with a monotonic `seq` number scoped to the session. The client buffers and renders events in `seq` order, not arrival order. Use a Redis-backed sequence counter (via ACA sidecar or Azure Cache for Redis) to ensure cross-instance sequence consistency.
- 📍 **Phase**: Streaming protocol design — define the event schema (including `seq`) before writing the first SSE handler.

---

## 6. Teams Bot

### Conversation Context Sync Between Teams and Web UI
- ⚠️ **Risk**: A user who starts a remediation in the web UI and then follows up in Teams (or vice versa) will encounter a context split — the Teams bot has its own conversation state, the web UI has its own session. The agent sees two separate conversations and loses the thread.
- 🛡️ **Prevention**: Use a single session store (Cosmos DB) keyed by user identity (Entra OID), not by channel. Both the Teams bot adapter and the web UI SSE handler read/write the same session document. The agent layer is channel-agnostic; channel is just metadata.
- 📍 **Phase**: Session architecture — establish the unified session model before building either channel.

### Adaptive Card 30-Day Expiry
- ⚠️ **Risk**: Adaptive Cards in Teams become non-interactive after 30 days. Approval cards for remediation actions that go unacknowledged (vacation, backlog) silently expire. The agent may interpret no response as approval or stall indefinitely.
- 🛡️ **Prevention**: Set explicit expiry metadata on every approval card. The agent must treat card expiry as an explicit rejection, not a timeout. Implement a background job that sweeps for expired pending approvals and marks them `EXPIRED` in Cosmos, triggering a notification to the approver.
- 📍 **Phase**: Approval workflow design — handle expiry state before any approval flow is shipped.

### Teams Throttling (600 Messages/Min Per Bot)
- ⚠️ **Risk**: During an alert storm, multiple simultaneous agent sessions each sending progress updates to Teams can collectively hit the 600 msg/min bot throttle. Throttled messages are dropped silently (no error to the bot), so users see incomplete or missing notifications.
- 🛡️ **Prevention**: Implement a priority queue for outbound Teams messages with rate limiting at 500 msg/min (20% headroom). Batch low-priority status updates into digest messages. Only route critical/approval-required messages as individual cards. Monitor the outbound queue depth as an ACA scaling metric.
- 📍 **Phase**: Bot infrastructure — implement the queue before any multi-session alert scenario is tested.

---

## 7. Cross-Subscription Auth

### Entra Agent ID (Preview) Instability
- ⚠️ **Risk**: Entra Agent ID is Preview. Token issuance can fail intermittently, provisioning via API has undocumented race conditions, and the permission model may change between preview updates — silently breaking agent-to-agent auth.
- 🛡️ **Prevention**: Implement a token acquisition retry with exponential backoff (3 attempts, max 30s). Build a health-check endpoint that validates Agent ID token issuance at startup and fails fast if it cannot acquire a token. Pin the Entra Agent ID API version in all SDK/REST calls.
- 📍 **Phase**: Auth infrastructure — validate Agent ID stability in a sandbox before depending on it in any critical path.

### Managed Identity Cold-Start in Container Apps
- ⚠️ **Risk**: When a Container App scales from zero (or a new revision spins up), the managed identity token endpoint is not immediately available. The first credential acquisition attempt fails, which crashes any agent that initializes auth in the constructor.
- 🛡️ **Prevention**: Use `DefaultAzureCredential` with retry. Defer credential acquisition to first use, not startup. Add a readiness probe that confirms token acquisition before the container is marked healthy. ACA will not route traffic until the probe passes.
- 📍 **Phase**: Container deployment — configure probes before going beyond dev environments.

### Cross-Subscription RBAC Permission Errors
- ⚠️ **Risk**: Agents operating across subscriptions (e.g., reading from a monitoring subscription, remediating in a workload subscription) hit RBAC gaps where a managed identity has rights in sub-A but not sub-B. The error often surfaces as a generic 403, masking which resource and which assignment is missing.
- 🛡️ **Prevention**: Maintain a `role-assignments.tf` that declares every cross-subscription RBAC binding explicitly. Run `az role assignment list` as part of the CI pipeline to validate actual state matches declared state. Instrument 403 errors with enough context (subscription, resource type, operation) to identify the gap immediately.
- 📍 **Phase**: Terraform + CI — enforce before multi-subscription resources are provisioned.

---

## 8. Custom Arc MCP Server

### Arc Connectivity for Disconnected Resources
- ⚠️ **Risk**: Arc-connected servers behind strict firewalls or in air-gapped environments may have intermittent or degraded connectivity to Azure. The Arc MCP Server will return stale data or timeout without clearly indicating that the connected machine is offline.
- 🛡️ **Prevention**: The Arc MCP Server must expose a `connectivity_status` field on every resource response, sourced from the Arc agent heartbeat. Agents must check this field before taking any action on an Arc resource and treat `DISCONNECTED` as a hard block, not a warning.
- 📍 **Phase**: Arc MCP server design — include connectivity status in the API contract from day one.

### Arc Extension Health Going Stale Silently
- ⚠️ **Risk**: Arc extension health statuses (monitoring agent, policy extension, custom script) can become stale in the Arc resource model — showing "Succeeded" for an extension that has since crashed or been uninstalled. The MCP server reflects this stale state to agents.
- 🛡️ **Prevention**: Supplement Arc API health data with a direct heartbeat check (e.g., query the Log Analytics workspace for a heartbeat event within the last 5 minutes) before reporting extension health. Flag any resource where API health and heartbeat disagree as `HEALTH_UNCERTAIN`.
- 📍 **Phase**: Arc MCP tool implementation — build the heartbeat cross-check before any remediation tool uses Arc health.

### REST API Pagination for Large Arc Estates
- ⚠️ **Risk**: Arc REST APIs return paginated results with `nextLink`. Tools that don't implement pagination return only the first page (typically 100 records), silently missing resources. An agent that "lists all Arc servers" and gets 100 of 3,000 will generate incomplete remediation plans without any error.
- 🛡️ **Prevention**: All Arc MCP list tools must follow `nextLink` until exhausted, or accept explicit `limit`/`offset` parameters and return a `total_count` field. Add an integration test against a seeded estate of > 100 records that validates count. Never use a list tool result without checking `total_count` vs returned count.
- 📍 **Phase**: Arc MCP tool implementation — pagination is not optional, test it before release.

---

## 9. Terraform

### Fabric and Foundry Resources Require `azapi`
- ⚠️ **Risk**: Fabric Eventhouse, Activator, Foundry Hosted Agents, and Entra Agent ID have no `azurerm` provider support (or incomplete support). Engineers who reach for `azurerm` first will either find no resource type or use outdated resource definitions that silently deploy incorrect configurations.
- 🛡️ **Prevention**: Maintain an explicit registry in `docs/terraform-provider-map.md` that lists every resource and its authoritative provider (`azurerm` vs `azapi`). Add a CI lint rule that flags any `azapi_resource` for a service that has a native `azurerm` equivalent, and any `azurerm_resource` for services known to require `azapi`. Pin `azapi` provider version.
- 📍 **Phase**: Terraform setup — establish the provider map before any infrastructure module is written.

### State Management Across Subscriptions
- ⚠️ **Risk**: Multi-subscription deployments with a single Terraform state file create lock contention and blast radius issues. A failed apply in the monitoring subscription can leave the workload subscription in a partial state. Separate state files without cross-references cause drift.
- 🛡️ **Prevention**: Use one state file per subscription per environment (e.g., `monitoring-prod.tfstate`, `workload-prod.tfstate`). Use `terraform_remote_state` data sources (read-only) for cross-subscription references. Never use `depends_on` across state boundaries — use data sources and output values instead.
- 📍 **Phase**: Terraform architecture — establish state boundaries before any multi-subscription resource is declared.

### Entra Agent ID Provisioning Gaps
- ⚠️ **Risk**: Entra Agent ID provisioning via `azapi` has race conditions — the agent identity may not be fully propagated in Entra before downstream role assignments are applied, causing Terraform applies to fail non-deterministically.
- 🛡️ **Prevention**: Add an explicit `time_sleep` resource (30–60s) after Agent ID provisioning before any role assignments that depend on it. Flag this in code comments as a known API propagation delay, not a hack. Track the issue against the Entra Agent ID API and remove the sleep when propagation becomes synchronous.
- 📍 **Phase**: Terraform agent identity module — add the sleep on first implementation.

---

## 10. Operational

### LLM Token Cost Explosions in Agent Loops
- ⚠️ **Risk**: A poorly scoped tool (e.g., a Monitor query returning 50,000 log rows dumped into agent context) or a retry loop without a ceiling can burn thousands of dollars in minutes. Without per-session cost tracking, this goes unnoticed until the billing alert fires.
- 🛡️ **Prevention**: Instrument every agent session with a `token_budget` enforced at the orchestration layer. Store cumulative token usage in Cosmos DB (updated per LLM call). Alert (and abort) when session cost exceeds configurable thresholds (e.g., $1 warn, $5 abort). All tool results must be truncated/summarized before injection into context.
- 📍 **Phase**: Agent runtime — instrument before any agent is exposed to real workloads.

### Alert Storms from Fabric Activator
- ⚠️ **Risk**: During a real incident (e.g., a node pool outage affecting 200 resources), Activator can fire hundreds of triggers simultaneously. Each trigger may spin up an agent session, overwhelming the ACA scale-out limits, Cosmos write throughput, and the Teams bot message queue simultaneously.
- 🛡️ **Prevention**: Implement an alert correlation layer (Redis-backed, 60s window) that deduplicates alerts by resource group and alert type before they reach the agent orchestrator. Group correlated alerts into a single "incident" session rather than spawning one session per alert. Define max concurrent agent sessions per incident type.
- 📍 **Phase**: Incident orchestration — build correlation before production alert rules are enabled.

### Cosmos RU Spikes on Concurrent Agent Sessions
- ⚠️ **Risk**: Each active agent session generates frequent Cosmos reads/writes (context updates, tool result caching, approval state). During an alert storm with 50+ concurrent sessions, this causes RU exhaustion, leading to `429 Too Many Requests` errors that corrupt session state mid-remediation.
- 🛡️ **Prevention**: Use Cosmos autoscale with a minimum RU floor sized for expected concurrent sessions (benchmark: ~100 RU/session/min). Partition the session container by `tenantId` + `sessionId` to distribute load. Implement a session state write coalescer (batch writes within 500ms windows) to reduce write frequency. Monitor RU consumption as a primary ACA scaling signal.
- 📍 **Phase**: Data architecture — size and partition Cosmos before load testing.

### Remediation Safety: Approve-Then-Stale Problem
- ⚠️ **Risk**: A user approves a remediation action (e.g., "restart deployment X") via Adaptive Card. By the time the agent executes the action, the resource state has changed (the deployment already self-healed, or a new deployment is in progress). Executing stale-approved actions causes unintended disruption.
- 🛡️ **Prevention**: Every approved action must include a pre-execution state snapshot hash. Before executing, the agent re-reads the resource state and compares it against the snapshot. If state has diverged beyond a configurable threshold, the action is aborted and the user is notified to re-approve. Approval is valid for a maximum configurable TTL (recommend 15 minutes for destructive actions).
- 📍 **Phase**: Remediation workflow — build the pre-execution state check before any destructive action tool is registered.
