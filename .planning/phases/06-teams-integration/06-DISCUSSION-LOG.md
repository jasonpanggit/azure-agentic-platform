# Phase 6: Teams Integration - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-27
**Phase:** 06-teams-integration
**Areas discussed:** Bot hosting & architecture, Streaming response in Teams, Adaptive Card action pattern, Thread sharing & escalation

---

## Bot Hosting & Architecture

| Option | Description | Selected |
|--------|-------------|----------|
| Separate TS Container App | Separate services/teams-bot/ TypeScript Container App. Teams SDK TypeScript is GA, Python is Preview. Clean service boundary, own Dockerfile and Container App. | ✓ |
| Extend api-gateway (Python) | Add /teams/messages to existing FastAPI service. Uses Python Teams SDK (Preview). Mixes Teams bot concerns into the thin gateway. | |

**User's choice:** Separate TypeScript Container App

---

| Option | Description | Selected |
|--------|-------------|----------|
| Call api-gateway REST | Bot calls POST /api/v1/chat on api-gateway. Api-gateway owns all Foundry thread management. | ✓ |
| Direct Foundry SDK from bot | Bot imports azure-ai-projects directly. Duplicates thread management logic. | |

**User's choice:** Call api-gateway REST (consistent with Phase 5 D-09)

---

| Option | Description | Selected |
|--------|-------------|----------|
| No APIM in Phase 6 | api-gateway remains direct public ingress. Defer to Phase 7 hardening. | ✓ |
| Add APIM Standard v2 now | Add APIM as front-door for all APIs. ~$400/month. | |
| Dedicated /teams/* prefix | Teams traffic logically separated on api-gateway. No APIM. | |

**User's choice:** No APIM — final deferral to Phase 7

---

## Streaming Response in Teams

| Option | Description | Selected |
|--------|-------------|----------|
| Typing indicator + full response | Sends typing indicator, waits for complete Foundry run, posts full response. Simple, reliable. | ✓ |
| Progressive card edits (polling) | Posts initial card, edits every few seconds. Complex, chatty, rate limit risk. | |
| Token-batched SSE streaming | Streams tokens from api-gateway SSE, batches every 2 seconds, edits incrementally. Most complex. | |

**User's choice:** Typing indicator + full response

---

| Option | Description | Selected |
|--------|-------------|----------|
| 30s timeout, 120s max | Interim message at 30s, max 120s total before failure deep-link. | ✓ |
| 60s timeout, fail fast | 60s flat, fail with Web UI redirect message. | |
| No bot-level timeout | Let api-gateway/Foundry handle timeouts. | |

**User's choice:** 30s interim, 120s max

---

## Adaptive Card Action Pattern

| Option | Description | Selected |
|--------|-------------|----------|
| Action.Http — direct to api-gateway | Approve/Reject POST directly to api-gateway approval endpoints. Simple, no Bot Framework registration needed. Teams shows success/error banner. | ✓ |
| Action.Execute — in-place card updates | Routes through bot endpoint. Card updates in-place. Requires bot registration as card origin. More complex. | |
| Hybrid: Execute for approvals, OpenUrl for alerts | Different actions per card type. | |

**User's choice:** Action.Http — consistent with Phase 5 teams_notifier.py stub

---

| Option | Description | Selected |
|--------|-------------|----------|
| Post follow-up outcome message | Bot posts new message "Approved by [UPN]. Running." triggered by api-gateway notify callback. | ✓ |
| Edit original card in-place | Bot edits original approval card via message update API. Requires tracking Teams message IDs. | |
| No explicit outcome update | Standard Teams success banner only. | |

**User's choice:** Post follow-up outcome message (avoids message ID tracking complexity)

---

## Thread Sharing & Escalation

| Option | Description | Selected |
|--------|-------------|----------|
| Incident-id lookup in Cosmos DB | Bot looks up existing thread_id from incidents record by incident_id. New thread for free-form messages. | ✓ |
| Teams channel/thread → Foundry thread mapping | 1:1 mapping stored in new Cosmos DB container. | |
| New thread per message (no sharing) | No cross-surface sharing. | |

**User's choice:** Incident-id lookup — satisfies TEAMS-004 cleanly

---

| Option | Description | Selected |
|--------|-------------|----------|
| Background loop in Teams bot Container App | setInterval every 2 minutes. Queries api-gateway for pending approvals older than N minutes. | ✓ |
| Dedicated cron Container App Job | Separate Container App Job on schedule. | |
| Cosmos DB change-feed listener on api-gateway | TTL-based trigger on approval records. | |

**User's choice:** Background loop in Teams bot (keeps all Teams logic in one service)

---

| Option | Description | Selected |
|--------|-------------|----------|
| Default 15 min, configurable via env | ESCALATION_INTERVAL_MINUTES env var. Loop checks every 2 min. | ✓ |
| 30 min default, two-reminder pattern | Match approval expiry, two reminders. | |
| No default — must be configured | Requires operator config at deploy time. | |

**User's choice:** 15 minutes default, configurable

---

## Claude's Discretion

- Teams bot TypeScript project structure
- Bot framework setup details (activity handler, bot manifest)
- Exact Adaptive Card JSON schemas
- In-memory vs. Teams conversation state store for per-user thread_id
- Container App size for teams-bot
- Bot Entra app registration details
- Error handling and retry logic

## Deferred Ideas

- APIM Standard v2 → Phase 7 (final deferral)
- Python Teams SDK → re-evaluate at Phase 7 if SDK reaches GA
- Action.Execute for in-place card updates → Phase 7 if needed
- Teams message ID tracking for in-place card editing → deferred
