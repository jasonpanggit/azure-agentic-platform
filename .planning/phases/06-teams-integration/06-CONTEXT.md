# Phase 6: Teams Integration - Context

**Gathered:** 2026-03-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Deliver a Teams bot as a co-equal interface to the Web UI — bidirectional agent conversations, alert Adaptive Cards, approval flow, and shared Foundry thread context across both surfaces.

Specifically:
1. **Teams bot service** — `services/teams-bot/` TypeScript Container App using the new `@microsoft/teams.js` SDK (GA). Two-way conversations routed to the Orchestrator via the existing api-gateway REST endpoints.
2. **Alert cards** — Structured Adaptive Card (v1.5) posted to a configured Teams channel when an alert fires; includes resource name, severity, subscription, timestamp, and "Investigate" action button.
3. **Approval flow** — Remediation approval Adaptive Cards posted to Teams (replacing/extending the Phase 5 `teams_notifier.py` stub); operator Approve/Reject via `Action.Http` directly to api-gateway endpoints.
4. **Cross-surface thread sharing** — Teams bot looks up the Foundry `thread_id` from Cosmos DB by `incident_id`; both Teams and Web UI operate on the same thread.
5. **Escalation reminders** — Background loop in the Teams bot Container App checks for unacted approvals and re-posts reminders.
6. **Outcome cards** — After an approved remediation executes, the bot posts a structured outcome card (success/failure, duration, resource state).

**No new IaC** — Phase 6 is application code only; the Container App environment and Cosmos DB are already provisioned. A new Container App registration is needed for `services/teams-bot/` (follows Phase 2 pattern).

</domain>

<decisions>
## Implementation Decisions

### Bot Hosting & Architecture
- **D-01:** Teams bot lives in a **separate `services/teams-bot/` TypeScript Container App**. Language: TypeScript (not Python) — `@microsoft/teams.js` TypeScript SDK is GA; the Python equivalent is Preview. Clean service boundary, own Dockerfile, own Container App deployment. The bot does NOT own Foundry thread management.
- **D-02:** The Teams bot connects to the agent layer by **calling the existing api-gateway REST endpoints** (`POST /api/v1/chat`, `GET /api/v1/incidents/{id}`). No direct `azure-ai-projects` SDK calls from the bot. Api-gateway remains the single owner of Foundry thread lifecycle — consistent with D-09/D-10 from Phase 5.
- **D-03:** **No APIM in Phase 6.** The api-gateway continues as the direct public ingress for both Web UI and Teams bot. APIM Standard v2 is deferred to Phase 7 Quality & Hardening (final deferral — should be evaluated at Phase 7 planning with production traffic data).
- **D-04:** The existing `services/api-gateway/teams_notifier.py` (Phase 5 stub) is **superseded by the Teams bot**. The bot receives proactive messages from the api-gateway via a new internal webhook endpoint (`POST /teams/internal/notify`) on the Teams bot Container App. The api-gateway calls this endpoint to trigger alert cards and outcome cards.

### Streaming Response Delivery
- **D-05:** Streaming strategy: **typing indicator + full response**. When an operator sends a message, the bot sends a Teams typing indicator, calls `POST /api/v1/chat` on the api-gateway (which creates a Foundry thread run), waits for the run to complete, then posts the full response as a single Teams reply. No SSE, no progressive card edits.
- **D-06:** Timeout behavior: **30 seconds before interim message, 120 seconds max**. If the Foundry run has not completed within 30 seconds, the bot posts `"Still working on this — complex investigation in progress..."`. The bot continues waiting up to 120 seconds total. If 120 seconds is exceeded, the bot posts `"The investigation is taking longer than expected. Check the Web UI for full results."` with a deep link to the incident in the Web UI.
- **D-07:** The api-gateway's existing `POST /api/v1/chat` endpoint is used for operator-initiated Teams conversations. The Teams bot passes the authenticated operator's UPN (from the Teams activity) as `user_id`; the bot itself authenticates to the api-gateway using its managed identity token (same Entra auth pattern as all other callers).

### Adaptive Card Action Pattern
- **D-08:** Approval Adaptive Cards use **`Action.Http`** (consistent with the Phase 5 `teams_notifier.py` stub). Approve/Reject buttons POST directly to `api-gateway` approval endpoints (`/api/v1/approvals/{id}/approve` and `/api/v1/approvals/{id}/reject`). No Bot Framework registration required for the card action itself. Teams shows a success/error banner on click.
- **D-09:** Post-decision outcome communication: after an operator approves/rejects, the **bot posts a new follow-up message** in the Teams channel: `"Approved by [operator UPN]. Remediation is now running."` or `"Rejected by [operator UPN]. Proposal closed."`. This is triggered by the api-gateway calling the Teams bot's internal notify endpoint when the approval record is updated. The bot does NOT edit the original approval card in-place (avoids tracking Teams message IDs per approval).
- **D-10:** Alert "Investigate" button uses **`Action.OpenUrl`** — opens the Web UI deep link to the incident. Format: `{WEB_UI_PUBLIC_URL}/incidents/{incident_id}`. No bot registration needed for this action.
- **D-11:** The api-gateway's `teams_notifier.py` is replaced by calls to the new Teams bot internal notify endpoint. The api-gateway sends a structured JSON payload to `POST /teams/internal/notify` with `card_type: "alert" | "approval" | "outcome"` and the relevant payload. The bot renders the correct Adaptive Card from this payload.

### Cross-Surface Thread ID Sharing (TEAMS-004)
- **D-12:** **Incident-id-based thread lookup**: when a Teams message arrives with an `incident_id` (e.g., from the "Investigate" button on an alert card, or an operator typing `/investigate INC-123`), the bot calls the api-gateway to look up the Cosmos DB incidents record and retrieves the existing `thread_id`. The bot then continues that Foundry thread via `POST /api/v1/chat` with the existing `thread_id`.
- **D-13:** For **free-form messages without an incident_id**, the bot creates a new Foundry thread via `POST /api/v1/chat` (no `incident_id` in the payload). The response from the api-gateway includes the new `thread_id`, which the bot stores in a per-user conversation state (in-memory or Teams conversation state store) for follow-up messages in the same Teams conversation.
- **D-14:** Both Web UI and Teams surfaces use the same `thread_id` for the same incident. The Foundry thread history is accessible from either surface through the api-gateway. This satisfies TEAMS-004 end-to-end.

### Escalation Reminder Scheduler (TEAMS-005)
- **D-15:** Escalation runs as a **background `setInterval` loop in the Teams bot Container App** — checks every 2 minutes. Queries the api-gateway `GET /api/v1/approvals?status=pending` endpoint (new endpoint needed on api-gateway). For each pending approval older than `ESCALATION_INTERVAL_MINUTES`, the bot posts a reminder card to the channel.
- **D-16:** Default escalation interval: **15 minutes**, configurable via `ESCALATION_INTERVAL_MINUTES` environment variable on the Teams bot Container App. Background loop polls every 2 minutes.
- **D-17:** Reminder card format: re-posts the original approval information with a `"⚠️ Reminder: Approval required"` header, original action description, remaining time before expiry, and a direct link to the Web UI approval view (`{WEB_UI_PUBLIC_URL}/approvals/{approval_id}`).

### Claude's Discretion
- Teams bot TypeScript project structure within `services/teams-bot/` (module layout, entry point)
- `@microsoft/teams.js` bot framework setup details (activity handler, bot registration manifest)
- Exact Adaptive Card JSON schemas beyond what's required by TEAMS-002 requirements
- In-memory vs. Teams conversation state store for tracking per-user `thread_id` in free-form conversations
- Container App container size for `services/teams-bot/` (Node.js runtime)
- Teams bot app manifest format (ID, permissions, scopes)
- Error handling and retry logic for Teams API calls
- Teams bot Entra app registration details (client credentials grant type for api-gateway auth)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 6 Requirements
- `.planning/REQUIREMENTS.md` §TEAMS — TEAMS-001 through TEAMS-006: full Teams integration requirements (bot deployment, alert cards, approval flow, cross-surface thread sharing, escalation, outcome cards)
- `.planning/ROADMAP.md` §"Phase 6: Teams Integration" — 6 success criteria define Phase 6 acceptance tests

### Technology Stack
- `CLAUDE.md` §"Teams Integration" — New Teams SDK (`@microsoft/teams.js` + `@microsoft/teams.ai`); TypeScript is GA, Python is Preview; CLI bootstrap via `npx @microsoft/teams.cli@latest new`; Adaptive Card approval flow pattern; avoid legacy `botbuilder` SDK
- `CLAUDE.md` §"Core Agent Framework" — Microsoft Agent Framework 1.0.0rc5; Foundry thread management
- `CLAUDE.md` §"Azure Integration Layer" — `azure-ai-projects` 2.0.1; thread management APIs

### Existing Implementation — Must Read Before Building
- `services/api-gateway/teams_notifier.py` — Phase 5 outbound-only Teams notifier (superseded by Phase 6 bot); study the Adaptive Card JSON structure and `Action.Http` pattern before building the new bot
- `services/api-gateway/approvals.py` — approval lifecycle (get, approve, reject, expiry check, Foundry thread resume); the Teams bot calls these via REST — do NOT duplicate this logic
- `services/api-gateway/main.py` — existing FastAPI app; new endpoint `GET /api/v1/approvals?status=pending` needed for escalation checker; new internal webhook endpoint NOT on api-gateway (it's on the Teams bot itself)
- `services/api-gateway/chat.py` — `create_chat_thread()` pattern; Teams bot uses `POST /api/v1/chat` with same interface
- `agents/shared/envelope.py` — typed message envelope schema; Teams bot interactions use `message_type: "incident_handoff"` for conversation routing
- `services/web-ui/` — deep-link URL patterns for Web UI (incidents, approvals) used in Adaptive Card "Investigate" and reminder buttons

### Infrastructure
- `CLAUDE.md` §"Infrastructure as Code (Terraform)" — Container App deployment pattern; `azurerm_container_app` for new `services/teams-bot/` service; follows Phase 2 agent container pattern

### Prior Phase Decisions
- `.planning/phases/05-triage-remediation-web-ui/05-CONTEXT.md` — D-09 (approval endpoints on api-gateway, shared by Web UI and Teams); D-10 (write-then-return Foundry parking); D-11 (Resource Identity Certainty); D-13 (30-min approval expiry)
- `.planning/phases/02-agent-core/02-CONTEXT.md` — D-09 (api-gateway as standalone FastAPI); D-10 (Entra Bearer token auth); D-11 (Foundry thread dispatch pattern)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `services/api-gateway/teams_notifier.py` — Adaptive Card v1.5 JSON structure and `Action.Http` button pattern is directly reusable in the Teams bot. The card body, FactSet, and action format should be replicated in TypeScript.
- `services/api-gateway/approvals.py` — approval lifecycle is complete; Teams bot only needs to call the REST endpoints, not re-implement the logic
- `services/api-gateway/chat.py` — `create_chat_thread()` establishes the Foundry envelope format; Teams bot replicates the same `incident_handoff` message_type envelope
- `services/api-gateway/auth.py` — Entra Bearer token validation pattern; Teams bot's managed identity token is the same auth flow as all other callers

### Established Patterns
- Service layout: `services/{name}/` with own `Dockerfile`, `requirements.txt`/`package.json`, and deployed as Container App — Teams bot follows the same pattern as `services/api-gateway/`, `services/web-ui/`, `services/arc-mcp-server/`
- Container App deployment: per-service `azurerm_container_app` resource in Terraform, system-assigned managed identity, public ingress for inbound traffic
- Entra auth: all callers authenticate to api-gateway with Bearer tokens; Teams bot uses its own managed identity client credentials flow

### Integration Points
- `services/teams-bot/` — new Container App; **inbound** from Teams (bot messages, Adaptive Card webhooks); **outbound** to api-gateway (`/api/v1/chat`, `/api/v1/incidents/{id}`, `/api/v1/approvals?status=pending`)
- `services/api-gateway/main.py` — needs one new endpoint: `GET /api/v1/approvals?status=pending` for the escalation checker to query
- `services/api-gateway/teams_notifier.py` — the api-gateway still needs to call the Teams bot to post proactive cards (alert cards, outcome cards); instead of posting directly via webhook URL, it calls `POST /teams/internal/notify` on the Teams bot Container App
- Cosmos DB `incidents` container (Phase 4) — Teams bot queries via api-gateway to look up `thread_id` by `incident_id` for TEAMS-004 cross-surface routing

</code_context>

<specifics>
## Specific Ideas

- **Internal notify endpoint pattern** — The api-gateway needs to call back to the Teams bot for proactive card posting (alert cards, outcome cards). The bot exposes `POST /teams/internal/notify` (internal Container App VNet endpoint, not public). The api-gateway calls this endpoint with a structured payload containing `card_type` and card data. This is the inversion of the Phase 5 `teams_notifier.py` webhook approach — the bot is now in charge of rendering, not the api-gateway.
- **Escalation reminder query** — `GET /api/v1/approvals?status=pending` is needed on the api-gateway for the Teams bot's escalation background loop. This endpoint doesn't exist yet (Phase 5 only implemented per-thread approval listing). The planner should include this as a small api-gateway addition.
- **Teams bot app registration** — The bot requires an Azure AD app registration (or bot channel registration in Teams Dev Portal). This is application code / deployment config, not new Terraform IaC. The planner should include bot registration setup instructions.
- **Deep link URL format** — Adaptive Card "Investigate" buttons and reminder cards need the Web UI public URL. The Teams bot uses `WEB_UI_PUBLIC_URL` env var (consistent with the `API_GATEWAY_PUBLIC_URL` pattern in `teams_notifier.py`).

</specifics>

<deferred>
## Deferred Ideas

### APIM Standard v2
Phase 2 deferred APIM, Phase 5 deferred again — now **final deferral to Phase 7**. At Phase 7 planning, evaluate with production traffic data from both Web UI and Teams surfaces. At that point, the multiple APIs (chat, incidents, approvals, runbooks) justify APIM Standard v2 (~$400/month) for centralised JWT validation, rate limiting, and analytics. Do not re-evaluate before Phase 7.

### Teams Bot Python SDK
`microsoft.teams` Python SDK is Preview — if it reaches GA before Phase 7, evaluate migrating the bot to Python for language consistency with the rest of the platform. For now, TypeScript is the only production-safe choice.

### Action.Execute for In-Place Card Updates
Requires Bot Framework channel registration and more complex wiring. Deferred in favour of the simpler `Action.Http` + follow-up message pattern. Re-evaluate in Phase 7 if operators find the success banner (from `Action.Http`) insufficient UX.

### Teams Message ID Tracking
Editing original approval cards in-place requires storing the Teams message ID per approval in Cosmos DB. Deferred — the "post follow-up message" approach (D-09) avoids this complexity.

</deferred>

---

*Phase: 06-teams-integration*
*Context gathered: 2026-03-27*
