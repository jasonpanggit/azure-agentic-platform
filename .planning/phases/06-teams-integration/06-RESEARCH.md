# Phase 6: Teams Integration - Research

**Researched:** 2026-03-27
**Phase:** 06-teams-integration
**Requirements:** TEAMS-001, TEAMS-002, TEAMS-003, TEAMS-004, TEAMS-005, TEAMS-006

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Critical Risk: Action.Http vs Action.Execute](#2-critical-risk-actionhttp-vs-actionexecute)
3. [New Teams SDK vs Bot Framework SDK](#3-new-teams-sdk-vs-bot-framework-sdk)
4. [Azure Bot Service Registration](#4-azure-bot-service-registration)
5. [Proactive Messaging Architecture](#5-proactive-messaging-architecture)
6. [Cross-Surface Thread Sharing (TEAMS-004)](#6-cross-surface-thread-sharing-teams-004)
7. [Escalation Scheduler Design (TEAMS-005)](#7-escalation-scheduler-design-teams-005)
8. [API Gateway Changes Required](#8-api-gateway-changes-required)
9. [Container App Deployment Considerations](#9-container-app-deployment-considerations)
10. [Teams App Manifest & Registration](#10-teams-app-manifest--registration)
11. [Authentication Flow Analysis](#11-authentication-flow-analysis)
12. [Existing Code Reuse Map](#12-existing-code-reuse-map)
13. [Testing Strategy](#13-testing-strategy)
14. [Risk Register](#14-risk-register)
15. [Recommended Plan Decomposition](#15-recommended-plan-decomposition)

---

## 1. Executive Summary

Phase 6 delivers a Teams bot as a co-equal interface to the Web UI. The bot is a **TypeScript Container App** (`services/teams-bot/`) that communicates with the existing api-gateway REST endpoints. Six requirements (TEAMS-001 through TEAMS-006) cover bidirectional conversation, 4 card types (alert, approval, outcome, reminder), cross-surface thread sharing, and escalation reminders.

### Key Findings

1. **Action.Http is NOT supported in Microsoft Teams** for bot-delivered Adaptive Cards. The CONTEXT.md decision D-08 specifying `Action.Http` needs to be reconciled. The working alternatives are:
   - **Action.Execute** (Universal Actions) -- requires bot registration and `onAdaptiveCardInvoke` handler, but provides in-card action handling and card refresh.
   - **Action.Http** works ONLY for Outlook Actionable Messages and some Teams connector-posted cards, NOT for cards sent by bots via the Bot Framework.
   - The implementation must use `Action.Execute` with the bot handling the invoke and proxying to the api-gateway approval endpoints.

2. **The `@microsoft/teams.js` package** referenced in CLAUDE.md is the Teams JavaScript **client SDK** (for tabs, dialogs, etc.), NOT a bot framework. Building a Teams bot in TypeScript requires either the **Bot Framework SDK** (`botbuilder` package) or the **Teams AI Library** (`@microsoft/teams-ai`). The new Teams SDK referenced in CLAUDE.md may refer to a 2026-era package that replaces `botbuilder`, but as of current research the established production path is `botbuilder` + `@microsoft/teams-ai`.

3. **Proactive messaging** (alert cards, outcome cards, approval cards pushed to channels) requires saving a `ConversationReference` from the initial bot installation event. The bot must persist this reference to post cards to the channel later.

4. **No new Terraform IaC** is needed for infrastructure, but an **Azure Bot Service registration** (Azure AD app registration + Azure Bot resource) is required. This is a deployment/configuration concern, not a Terraform module.

5. **The existing api-gateway** needs one new endpoint: `GET /api/v1/approvals?status=pending` for the escalation scheduler. The existing approval endpoints need a minor adjustment: the `thread_id` is currently a query parameter, and the Teams `Action.Execute` flow needs to embed it in the card data payload.

---

## 2. Critical Risk: Action.Http vs Action.Execute

### The Problem

Decision D-08 in 06-CONTEXT.md states:
> Approval Adaptive Cards use **`Action.Http`** (consistent with the Phase 5 `teams_notifier.py` stub). Approve/Reject buttons POST directly to `api-gateway` approval endpoints.

The existing `teams_notifier.py` posts cards via an **Incoming Webhook URL** (`TEAMS_WEBHOOK_URL`). Incoming Webhooks are a **connector-based** mechanism. However:

1. **Office 365 Connectors are being deprecated** by Microsoft (retirement announced 2024-2025) in favor of Workflows (Power Automate) and bot-based messaging.
2. **`Action.Http` is NOT supported in Teams for bot-sent cards**. It is supported in Outlook Actionable Messages and historically in some connector-posted cards, but Teams bots use `Action.Execute` or `Action.Submit`.
3. The Phase 6 bot will send cards via the Bot Framework (not via webhook connectors), which means `Action.Http` will NOT work.

### Resolution Options

| Option | Verdict | Rationale |
|--------|---------|-----------|
| **A: Action.Execute (Universal Actions)** | **Recommended** | Bot receives `adaptiveCard/action` invoke activity; handles approve/reject in bot code; proxies to api-gateway; returns updated card. Full Teams support. Requires bot to handle invoke. |
| **B: Action.Submit** | Acceptable fallback | Bot receives `message/submitAction`; simpler but no card refresh capability. Less polished UX. |
| **C: Action.Http with webhook connector** | **Not viable** | Connectors being deprecated; would require hybrid bot+connector architecture; fragile. |

### Recommended Approach: Action.Execute

```json
{
  "type": "Action.Execute",
  "title": "Approve",
  "verb": "approve",
  "data": {
    "approval_id": "{approval_id}",
    "thread_id": "{thread_id}"
  },
  "style": "positive"
}
```

The bot's `onAdaptiveCardInvoke` handler:
1. Receives the invoke with `verb` and `data`
2. Calls `POST /api/v1/approvals/{approval_id}/approve` on the api-gateway (passing the operator's UPN from the Teams activity)
3. Returns an updated card showing "Approved by {operator}" -- this is the **in-place card update** that TEAMS-003 requires

**This actually ENABLES the original TEAMS-003 requirement** ("card updates in-place to reflect the decision") which D-09 explicitly deferred. With `Action.Execute`, in-place card updates are the default behavior -- the bot returns a new card from the invoke handler and Teams replaces the original card.

### Impact on UI-SPEC

The 06-UI-SPEC.md approval card schema uses `Action.Http`. This must be updated to `Action.Execute` with `verb` + `data` fields instead of `method` + `url` + `body`. The reminder card has the same issue. Alert and outcome cards use `Action.OpenUrl` which is fine.

### Impact on D-09 (Follow-Up Messages)

D-09 states: "the bot does NOT edit the original approval card in-place (avoids tracking Teams message IDs per approval)." With `Action.Execute`, the bot DOES update the card in-place as part of the invoke response -- this is simpler, not harder, because the Teams platform handles the card replacement automatically. No message ID tracking needed. The follow-up message pattern from D-09 can be kept as an ADDITIONAL confirmation, or removed as redundant.

---

## 3. New Teams SDK vs Bot Framework SDK

### CLAUDE.md States

> **TypeScript package**: `@microsoft/teams.js` + `@microsoft/teams.ai` (new Teams SDK)
> **CLI bootstrap**: `npx @microsoft/teams.cli@latest new typescript my-agent --template echo`

### Research Findings

| Package | Purpose | Status |
|---------|---------|--------|
| `@microsoft/teams-js` (v2.x) | Teams **client** SDK for tabs, dialogs, SSO in-browser | GA -- NOT for bots |
| `botbuilder` (v4.x) | Bot Framework SDK -- the established way to build Teams bots in Node.js/TypeScript | Maintenance mode but still functional |
| `@microsoft/teams-ai` (v1.x) | Teams AI Library -- modern wrapper over `botbuilder` for AI-powered bots | GA for TypeScript, actively developed |
| `@microsoft/teams.js` (new) | Referenced in CLAUDE.md as the "new Teams SDK" -- may be a 2026-era replacement | Per CLAUDE.md: GA for TypeScript |
| `@microsoft/teams.cli` | CLI scaffold tool referenced in CLAUDE.md | Per CLAUDE.md: available |

### Recommendation

CLAUDE.md explicitly states to use the new Teams SDK (`@microsoft/teams.js`) and to **avoid** the legacy `botbuilder` SDK. The planner should:

1. **Try the CLI scaffold first**: `npx @microsoft/teams.cli@latest new typescript my-agent --template echo` -- if this works and produces a functioning bot scaffold, use it.
2. **Fallback**: If the new SDK is not available or lacks bot capabilities, use `@microsoft/teams-ai` (the Teams AI Library) which is the Microsoft-recommended modern path and is GA for TypeScript.
3. **Do NOT use raw `botbuilder`** directly -- per CLAUDE.md's explicit guidance.

### Minimum Package Set (Fallback Path)

If using `@microsoft/teams-ai` as the fallback:

```json
{
  "dependencies": {
    "@microsoft/teams-ai": "^1.x",
    "botbuilder": "^4.x",
    "express": "^4.x",
    "@azure/identity": "^4.x",
    "adaptivecards": "^3.x"
  },
  "devDependencies": {
    "typescript": "^5.x",
    "@types/express": "^4.x",
    "@types/node": "^20.x"
  }
}
```

---

## 4. Azure Bot Service Registration

### What's Required

A Teams bot requires an **Azure Bot Service** registration that connects the bot's messaging endpoint to the Teams channel. This is NOT Terraform IaC (it's app-level config), but it must be set up before the bot can receive messages.

### Registration Steps

1. **Azure AD App Registration** (Entra ID):
   - Register a new application in Entra ID
   - Record the Application (client) ID = `BOT_ID`
   - Create a client secret = `BOT_PASSWORD` (or use managed identity certificate)
   - For single-tenant: restrict to the organization's tenant

2. **Azure Bot Resource**:
   - Create an Azure Bot resource in Azure Portal (or via `az bot create`)
   - Set `MicrosoftAppType` to `SingleTenant` (per project constraint: single-tenant)
   - Set `MicrosoftAppId` to the app registration's client ID
   - Set the messaging endpoint to: `https://<teams-bot-container-app-fqdn>/api/messages`

3. **Enable Teams Channel**:
   - In the Azure Bot resource, go to Channels and enable Microsoft Teams

4. **Teams App Manifest**:
   - Create a Teams app package (`manifest.json` + icons) and sideload or publish to the org app catalog

### Environment Variables for the Bot Container

| Variable | Source |
|----------|--------|
| `BOT_ID` | Azure AD app registration client ID |
| `BOT_PASSWORD` | Azure AD app registration client secret |
| `BOT_TYPE` | `"SingleTenant"` |
| `BOT_TENANT_ID` | Organization's Entra tenant ID |

### Managed Identity Alternative

Instead of client secret (`BOT_PASSWORD`), the bot can authenticate using the Container App's managed identity. This aligns with the project's zero-secret policy (AGENT-008). The Azure Bot resource supports managed identity authentication since 2024. This is the preferred approach.

---

## 5. Proactive Messaging Architecture

### Challenge

The Teams bot needs to proactively POST cards to a Teams channel without a user-initiated message. This is needed for:
- Alert cards (TEAMS-002) -- triggered by new incident in Cosmos DB
- Approval cards (TEAMS-003) -- triggered by high-risk remediation proposal
- Outcome cards (TEAMS-006) -- triggered by remediation completion
- Reminder cards (TEAMS-005) -- triggered by escalation scheduler

### How Proactive Messaging Works

1. **On bot installation** (the `onMembersAdded` or `onInstallationUpdate` event), the bot receives a `ConversationReference` object containing:
   - `serviceUrl` -- the Teams service URL for this tenant/region
   - `conversation.id` -- the channel conversation ID
   - `bot.id` -- the bot's identity in the conversation
   - `tenantId` -- the Entra tenant ID

2. **The bot MUST persist this `ConversationReference`** -- it is the only way to send messages later without a user-initiated message.

3. **To send a proactive message**, the bot uses `adapter.continueConversationAsync()` with the saved reference:
   ```typescript
   await adapter.continueConversationAsync(
     botId,
     savedConversationReference,
     async (turnContext) => {
       const card = buildAlertCard(payload);
       await turnContext.sendActivity({
         attachments: [CardFactory.adaptiveCard(card)]
       });
     }
   );
   ```

### Storage for ConversationReference

Per D-01, the bot does NOT own Foundry thread management and should be stateless where possible. Options:

| Storage | Verdict |
|---------|---------|
| In-memory (startup config) | Simplest; lost on restart; sufficient if only 1 channel |
| Environment variable | Not practical -- ConversationReference is a JSON object |
| Cosmos DB | Overkill for a single channel reference |
| **Bot installation event + env var for channel ID** | **Recommended**: Bot captures ConversationReference on first installation; stores in-memory; `TEAMS_CHANNEL_ID` env var identifies the target channel; bot re-acquires reference on restart via proactive installation endpoint |

### The Internal Notify Endpoint Flow

Per D-04 and D-11:
```
api-gateway --> POST /teams/internal/notify --> Teams bot --> Teams channel
```

1. Api-gateway fires a notification when an event occurs (incident created, approval needed, remediation complete)
2. Teams bot receives the notify request on its internal endpoint
3. Teams bot builds the appropriate Adaptive Card from the payload
4. Teams bot uses the saved `ConversationReference` to proactively post the card to the channel

### ConversationReference Bootstrap Problem

The bot cannot proactively message a channel until it has been installed in that team and has received at least one activity (which provides the `ConversationReference`). Solutions:

1. **Installation event capture**: When the bot is installed in a Teams team, the `onInstallationUpdate` handler fires. The bot saves the `ConversationReference` for the channel specified in `TEAMS_CHANNEL_ID`.
2. **Manual trigger**: After deployment, an admin sends a message to the bot in the target channel (e.g., "/hello") to trigger the ConversationReference capture.
3. **Graph API alternative**: Use the Microsoft Graph API to create a `ConversationReference` programmatically without an installation event. This requires `ChannelMessage.Send` permission.

Recommendation: Use option 1 (installation event capture) as the primary path, with option 2 as the manual fallback for initial setup.

---

## 6. Cross-Surface Thread Sharing (TEAMS-004)

### Design (from D-12, D-13, D-14)

Both Web UI and Teams share the same Foundry `thread_id` per incident. The mechanism:

1. **Incident-bound messages**: When a Teams message references an `incident_id` (via investigate button or `/investigate INC-123`), the bot calls the api-gateway to look up the Cosmos DB incident record and gets the existing `thread_id`. The bot then calls `POST /api/v1/chat` with that `thread_id` to continue the same Foundry thread.

2. **Free-form messages**: When an operator sends a free-form message with no incident context, the bot creates a new thread via `POST /api/v1/chat` and tracks the `thread_id` in per-user conversation state.

### API Gateway Chat Endpoint Analysis

The existing `POST /api/v1/chat` endpoint (`services/api-gateway/chat.py`) accepts:
```python
class ChatRequest(BaseModel):
    message: str
    incident_id: Optional[str] = None
```

And returns:
```python
class ChatResponse(BaseModel):
    thread_id: str
    status: str = "created"
```

**Current behavior**: The endpoint ALWAYS creates a new Foundry thread, even when `incident_id` is provided. For TEAMS-004, the endpoint needs to support **continuing an existing thread** when a `thread_id` is passed.

### Required API Gateway Change

The `ChatRequest` model needs a `thread_id` field:
```python
class ChatRequest(BaseModel):
    message: str
    incident_id: Optional[str] = None
    thread_id: Optional[str] = None  # Continue existing thread
```

When `thread_id` is provided:
- Skip thread creation
- Post the message to the existing thread
- Create a new run on the existing thread
- Return the same `thread_id`

When `incident_id` is provided but `thread_id` is not:
- Look up the incident in Cosmos DB to find its `thread_id`
- Continue that thread (same as above)

When neither is provided:
- Create a new thread (current behavior)

### Per-User Conversation State in Teams

For free-form conversations, the bot needs to track which Foundry `thread_id` is associated with the current Teams conversation. Options:

| Approach | Verdict |
|----------|---------|
| In-memory Map<conversationId, threadId> | Simple; lost on restart; OK for MVP |
| Teams Conversation State (Bot Framework) | Built-in state management; persisted if backed by storage |
| Cosmos DB per-conversation record | Durable; adds complexity |

Recommendation: Start with Bot Framework conversation state backed by in-memory storage. If durability is needed, swap to Cosmos DB backing later. The thread_id can also be re-derived from the incident record if lost.

---

## 7. Escalation Scheduler Design (TEAMS-005)

### From D-15, D-16, D-17

- Background `setInterval` loop every 2 minutes
- Queries `GET /api/v1/approvals?status=pending` on api-gateway
- For each pending approval older than `ESCALATION_INTERVAL_MINUTES` (default 15), posts a reminder card
- Tracks last reminder timestamp per `approval_id` in memory to avoid duplicate reminders within the same interval

### Implementation Considerations

1. **Single-instance safety**: If multiple bot container replicas are running, each instance runs its own `setInterval`. This could cause duplicate reminders. Solutions:
   - Set `maxReplicas: 1` on the Container App (acceptable for Phase 6; bot is not a high-throughput service)
   - Use a distributed lock in Cosmos DB (overkill for Phase 6)
   - Use leader election (overkill)

2. **Startup delay**: The escalation loop should not start until the bot has successfully acquired a `ConversationReference` for the target channel. Add a guard check.

3. **Error handling**: If the api-gateway is unreachable, the loop should log the error and retry on the next interval. No crash-on-failure.

4. **Expiry calculation**: The reminder card needs `remaining_minutes = (expires_at - now) / 60`. If remaining <= 0, the approval has expired and the scheduler should skip it (the api-gateway will have marked it expired).

### New API Gateway Endpoint

`GET /api/v1/approvals?status=pending` -- returns all pending approvals across all threads.

```python
@app.get("/api/v1/approvals", response_model=list[ApprovalRecord])
async def list_pending_approvals(
    status: str = "pending",
    token: dict[str, Any] = Depends(verify_token),
) -> list[ApprovalRecord]:
    """List approvals by status (TEAMS-005 escalation support)."""
    # Query Cosmos DB cross-partition for status == "pending"
    ...
```

**Note**: This is a cross-partition query in Cosmos DB (the `approvals` container is partitioned by `thread_id`). For a small number of pending approvals this is fine. If it becomes a bottleneck, add a GSI or secondary container.

---

## 8. API Gateway Changes Required

### Summary of Required Changes

| Change | File | Reason |
|--------|------|--------|
| Add `thread_id` field to `ChatRequest` | `models.py` | TEAMS-004: continue existing thread |
| Support thread continuation in `create_chat_thread()` | `chat.py` | TEAMS-004: skip thread creation when `thread_id` provided |
| Add `GET /api/v1/approvals?status=pending` endpoint | `main.py` | TEAMS-005: escalation scheduler query |
| Add `list_approvals_by_status()` function | `approvals.py` | TEAMS-005: cross-partition query for pending approvals |
| Refactor `teams_notifier.py` to call bot internal endpoint | `teams_notifier.py` | D-04: replace webhook URL with bot notify endpoint |
| Add incident lookup by `incident_id` | `chat.py` or new | TEAMS-004: resolve `thread_id` from `incident_id` |

### Minimal vs Full Refactor

The api-gateway changes are small and surgical. The `teams_notifier.py` replacement is the biggest change: instead of posting directly to a webhook URL, it calls `POST /teams/internal/notify` on the bot Container App. The core card-building logic moves to the TypeScript bot; the api-gateway just sends the structured payload.

---

## 9. Container App Deployment Considerations

### Teams Bot Container App

| Property | Value |
|----------|-------|
| Name | `teams-bot` |
| Runtime | Node.js 20 LTS |
| Port | `3978` (Teams convention) |
| Ingress | **External** (public) -- Teams service must reach the messaging endpoint |
| Min replicas | `1` (avoid cold start on Teams messages; escalation scheduler needs to run) |
| Max replicas | `1` (single instance for escalation scheduler dedup) |
| Health probe | `GET /health` |
| Messaging endpoint | `https://<fqdn>/api/messages` |
| Internal endpoint | `POST /teams/internal/notify` (also on port 3978, but accessed via internal VNet DNS) |

### Ingress Architecture

The bot has TWO callers with different ingress requirements:

1. **Microsoft Teams** -- calls `/api/messages` from the public internet (Teams service). Requires public ingress.
2. **Api-gateway** -- calls `/teams/internal/notify` from within the VNet. Should be internal-only.

Options:
- **Single public endpoint**: Both `/api/messages` and `/teams/internal/notify` are public. Secure the notify endpoint with an internal auth token or managed identity. Simplest.
- **Two Container Apps**: One public (messaging), one internal (notify). Overkill.
- **Single endpoint with path-based auth**: `/api/messages` validates Bot Framework tokens; `/teams/internal/notify` validates managed identity tokens. **Recommended.**

### Teams Message Endpoint Security

The Bot Framework SDK automatically validates incoming activities from Teams by checking the JWT token in the Authorization header against the Bot Framework authentication endpoints. No additional auth middleware needed for `/api/messages`.

For `/teams/internal/notify`, add a simple bearer token check (the api-gateway's managed identity token) or use a shared API key in a Key Vault secret.

---

## 10. Teams App Manifest & Registration

### Manifest Structure

```json
{
  "$schema": "https://developer.microsoft.com/en-us/json-schemas/teams/v1.17/MicrosoftTeams.schema.json",
  "manifestVersion": "1.17",
  "version": "1.0.0",
  "id": "{BOT_ID}",
  "developer": {
    "name": "AAP Platform",
    "websiteUrl": "https://example.com",
    "privacyUrl": "https://example.com/privacy",
    "termsOfUseUrl": "https://example.com/terms"
  },
  "name": {
    "short": "AAP Operations Bot",
    "full": "Azure Agentic Platform Operations Bot"
  },
  "description": {
    "short": "AI-powered infrastructure operations assistant",
    "full": "Investigate incidents, approve remediations, and monitor Azure infrastructure health"
  },
  "icons": {
    "outline": "outline.png",
    "color": "color.png"
  },
  "bots": [
    {
      "botId": "{BOT_ID}",
      "scopes": ["team", "personal"],
      "supportsFiles": false,
      "isNotificationOnly": false
    }
  ],
  "permissions": ["identity", "messageTeamMembers"],
  "validDomains": ["{CONTAINER_APP_FQDN}"]
}
```

### Deployment

The manifest is packaged as a `.zip` file with `manifest.json` + two icon PNGs (32x32 outline, 192x192 color). It is uploaded to the Teams Admin Center or sideloaded during development.

---

## 11. Authentication Flow Analysis

### Three Auth Flows in Phase 6

| Flow | From | To | Auth Method |
|------|------|----|-------------|
| Teams -> Bot | Microsoft Teams | Bot `/api/messages` | Bot Framework JWT (auto-validated by SDK) |
| Bot -> Api-Gateway | Teams bot | Api-gateway REST endpoints | Managed identity Bearer token (same as all callers) |
| Api-Gateway -> Bot | Api-gateway | Bot `/teams/internal/notify` | Internal auth (managed identity token or shared key) |

### Bot -> Api-Gateway Auth

The bot authenticates to the api-gateway the same way all other callers do: by acquiring a Bearer token from Entra for the api-gateway's audience/scope. The bot uses its Container App managed identity to acquire this token:

```typescript
import { DefaultAzureCredential } from "@azure/identity";

const credential = new DefaultAzureCredential();
const token = await credential.getToken(`api://${API_GATEWAY_CLIENT_ID}/.default`);
// Use token.token as Bearer token in HTTP requests
```

### Api-Gateway -> Bot Auth (Internal Notify)

Options:
1. **Managed identity token**: Api-gateway acquires a token for the bot's app registration audience. Bot validates the token. Most secure, consistent with project patterns.
2. **Shared API key**: Simpler; Key Vault-stored secret passed as `X-Internal-Key` header. Less elegant but functional.
3. **No auth (VNet-only)**: If the notify endpoint is only reachable within the VNet, network isolation provides the security. Simplest but least defense-in-depth.

Recommendation: Start with option 3 (VNet-only) and add managed identity auth in Phase 7 hardening if needed. The bot Container App's notify endpoint is accessed via internal DNS within the Container Apps environment, so it's not exposed to the public internet. The `/api/messages` endpoint is public but protected by Bot Framework JWT validation.

---

## 12. Existing Code Reuse Map

### Direct Port from Python to TypeScript

| Source (Python) | Target (TypeScript) | What to Port |
|-----------------|---------------------|--------------|
| `teams_notifier.py` `_build_adaptive_card()` | `cards/approval-card.ts` | Card JSON structure, FactSet layout, severity color mapping. **Change Action.Http to Action.Execute.** |
| `teams_notifier.py` risk color logic | `cards/approval-card.ts` | `"attention"` for critical, `"warning"` for high |
| `models.py` `ApprovalAction` | `types.ts` | `decided_by` field pattern |
| `models.py` `ChatRequest` | `types.ts` | `message`, `incident_id` fields |

### API Contracts to Consume (No Changes)

| Api-Gateway Endpoint | Used By Bot For |
|---------------------|-----------------|
| `POST /api/v1/chat` | Operator-initiated conversations (TEAMS-001) |
| `GET /api/v1/incidents/{id}` | Look up incident thread_id (TEAMS-004) |
| `POST /api/v1/approvals/{id}/approve` | Proxy approval from Action.Execute (TEAMS-003) |
| `POST /api/v1/approvals/{id}/reject` | Proxy rejection from Action.Execute (TEAMS-003) |

### API Contracts to Add

| New Endpoint | Used By |
|-------------|---------|
| `GET /api/v1/approvals?status=pending` | Escalation scheduler (TEAMS-005) |
| `POST /api/v1/chat` with `thread_id` support | Thread continuation (TEAMS-004) |

### UI-SPEC Card Schemas

The 06-UI-SPEC.md defines 4 card JSON schemas. These are directly implementable as TypeScript builder functions. The approval and reminder cards need `Action.Http` -> `Action.Execute` conversion.

---

## 13. Testing Strategy

### Unit Tests (TypeScript -- Jest or Vitest)

| Test Area | What to Test |
|-----------|-------------|
| Card builders | Each card builder returns valid Adaptive Card JSON; severity color mapping correct; all fields populated |
| Gateway client | HTTP calls to api-gateway endpoints are correctly formed; auth token is attached |
| Escalation scheduler | Correctly identifies overdue approvals; skips already-reminded approvals; computes remaining_minutes correctly |
| Notify route handler | Dispatches to correct card builder based on `card_type`; returns error for unknown types |
| Bot activity handler | Routes message activities to api-gateway chat; routes invoke activities to approval handler |

### Integration Tests (Against Live Bot)

| Test | What to Verify |
|------|---------------|
| TEAMS-001 | Send message to bot -> bot calls api-gateway -> response posted to Teams |
| TEAMS-002 | POST to `/teams/internal/notify` with `card_type: "alert"` -> card appears in channel |
| TEAMS-003 | POST approval notify -> card with Approve/Reject appears; click Approve -> api-gateway called -> card updates |
| TEAMS-004 | Start conversation in Web UI -> send follow-up in Teams -> same `thread_id` in Foundry |
| TEAMS-005 | Create pending approval -> wait > escalation interval -> reminder card posted |
| TEAMS-006 | POST outcome notify -> outcome card appears in channel |

### Mocking Strategy

- Mock the api-gateway HTTP calls in unit tests (intercept with `nock` or `msw`)
- Mock the Bot Framework adapter for testing activity handlers without a real Teams connection
- The api-gateway's own tests already cover approval lifecycle; bot tests only need to verify the HTTP call is made correctly

### CI Integration

Add a `teams-bot-api-gateway-ci.yml` workflow:
- TypeScript lint (`eslint`)
- Type check (`tsc --noEmit`)
- Unit tests (`vitest run --coverage`)
- Coverage threshold: 80%

---

## 14. Risk Register

| # | Risk | Impact | Likelihood | Mitigation |
|---|------|--------|------------|------------|
| R1 | `Action.Http` not supported in Teams for bot-sent cards | **HIGH** -- approval flow broken | **HIGH** -- confirmed by research | Use `Action.Execute` instead; update UI-SPEC; bot handles invoke and proxies to api-gateway |
| R2 | New Teams SDK (`@microsoft/teams.js`) may not exist as a bot framework | **MEDIUM** -- need to pick a different package | **MEDIUM** -- CLAUDE.md references it but research shows it's a client SDK | Fallback to `@microsoft/teams-ai` + `botbuilder`; try CLI scaffold first |
| R3 | ConversationReference lost on bot restart -- no proactive messaging | **HIGH** -- alert/approval cards cannot be posted | **MEDIUM** -- in-memory storage is volatile | Persist ConversationReference to Cosmos DB or capture on every bot installation event; set minReplicas=1 to reduce restart frequency |
| R4 | Escalation scheduler runs in multiple replicas causing duplicate reminders | **LOW** -- duplicate reminders are annoying but not harmful | **LOW** -- maxReplicas=1 mitigates | Set maxReplicas=1; add in-memory dedup tracking |
| R5 | Thread continuation requires new api-gateway `thread_id` parameter | **LOW** -- small code change | **HIGH** -- definitely needed | Include in Phase 6 api-gateway changes |
| R6 | Bot cold start delays causing Teams message timeout | **MEDIUM** -- first message after scale-to-zero takes >15s | **MEDIUM** -- Container Apps scales to zero by default | Set minReplicas=1; bot is lightweight Node.js |
| R7 | `thread_id` query parameter on approval endpoints breaks Action.Execute | **MEDIUM** -- Action.Execute passes data in card body, not URL query params | **HIGH** -- current approval endpoints expect `thread_id` as query param | Modify approval endpoints to accept `thread_id` in request body OR in card data |

---

## 15. Recommended Plan Decomposition

Based on the research, the following plan structure addresses all 6 requirements with minimal coupling between plans:

### Plan 06-01: Teams Bot Scaffold + Internal Notify Endpoint

**Scope:** Project setup, Express server, health endpoint, internal notify route, card builder stubs, Dockerfile, CI workflow.

**Requirements:** Foundation for all TEAMS-* requirements.

**Deliverables:**
- `services/teams-bot/` TypeScript project with `package.json`, `tsconfig.json`, `Dockerfile`
- Express server on port 3978 with `/health` and `/teams/internal/notify` routes
- Card builder functions for all 4 card types (alert, approval, outcome, reminder) -- using `Action.Execute` for approval/reminder cards
- `types.ts` with all payload interfaces
- `config.ts` with environment variable parsing
- `teams-bot-api-gateway-ci.yml` with lint, type check, unit tests, 80% coverage gate
- Unit tests for card builders and notify route

### Plan 06-02: Bot Framework Integration + Conversational Flow (TEAMS-001)

**Scope:** Bot Framework adapter, TeamsActivityHandler, message handling, api-gateway client, proactive messaging setup.

**Requirements:** TEAMS-001 (two-way conversation)

**Deliverables:**
- Bot adapter and activity handler (`bot.ts`)
- `/api/messages` endpoint for Teams Bot Framework
- `gateway-client.ts` -- HTTP client with managed identity auth for api-gateway
- Message activity handler: receives text -> calls `POST /api/v1/chat` -> posts response to Teams
- Typing indicator + 30s interim + 120s timeout logic (D-05, D-06)
- ConversationReference capture on installation
- Auth service for managed identity token acquisition
- Unit tests for bot handler and gateway client

### Plan 06-03: Approval Action Handler + Api-Gateway Changes (TEAMS-003, TEAMS-004)

**Scope:** `Action.Execute` invoke handler, api-gateway modifications for thread continuation and pending approvals listing.

**Requirements:** TEAMS-003 (approval flow), TEAMS-004 (cross-surface thread sharing)

**Deliverables:**
- `onAdaptiveCardInvoke` handler in bot for approve/reject verbs
- Card update response (in-place card update showing decision + operator UPN)
- Api-gateway: `ChatRequest.thread_id` field + thread continuation logic in `chat.py`
- Api-gateway: incident lookup for `thread_id` resolution by `incident_id`
- Api-gateway: `GET /api/v1/approvals?status=pending` endpoint
- Api-gateway: accept `thread_id` in approval request body (not just query param)
- Api-gateway: refactor `teams_notifier.py` to call bot's internal notify endpoint
- Unit tests for invoke handler and api-gateway changes

### Plan 06-04: Escalation Scheduler + Proactive Card Posting (TEAMS-002, TEAMS-005, TEAMS-006)

**Scope:** Background escalation loop, proactive card posting wiring, alert/outcome card triggers.

**Requirements:** TEAMS-002 (alert cards), TEAMS-005 (escalation), TEAMS-006 (outcome cards)

**Deliverables:**
- `escalation.ts` -- background scheduler with `setInterval(120000)`
- Escalation dedup logic (in-memory last-reminder map per approval_id)
- Proactive messaging wiring: `ConversationReference` storage + `continueConversationAsync` pattern
- Alert card posting via notify endpoint (triggered by api-gateway on incident creation)
- Outcome card posting via notify endpoint (triggered by api-gateway on remediation completion)
- Reminder card posting via escalation scheduler
- Unit tests for escalation scheduler and proactive messaging

### Plan 06-05: Teams App Manifest + Integration Testing

**Scope:** App manifest, deployment configuration, integration test stubs, documentation.

**Requirements:** All TEAMS-* (integration verification)

**Deliverables:**
- Teams app manifest (`manifest.json`, icons) in `services/teams-bot/appPackage/`
- Azure Bot Service registration documentation/scripts
- Container App deployment configuration (min/max replicas, env vars, health probes)
- Integration test stubs for all 6 success criteria
- Bot registration setup guide (`services/teams-bot/SETUP.md`)
- End-to-end smoke test: send message -> receive response

---

## Appendix A: Technology Version Pins

| Package | Version | Notes |
|---------|---------|-------|
| `@microsoft/teams-ai` | `^1.x` (latest) | Fallback if new Teams SDK unavailable |
| `botbuilder` | `^4.x` (latest) | Required by `@microsoft/teams-ai` |
| `adaptivecards` | `^3.x` | Type definitions for card building |
| `express` | `^4.x` | HTTP server |
| `@azure/identity` | `^4.x` | Managed identity token acquisition |
| `typescript` | `^5.x` | Compilation |
| `vitest` | `^2.x` | Unit testing |
| `eslint` | `^9.x` | Linting |

## Appendix B: Key File Reference

| File | Purpose | Phase 6 Relevance |
|------|---------|-------------------|
| `services/api-gateway/teams_notifier.py` | Phase 5 outbound card posting | Superseded; card JSON structure reusable |
| `services/api-gateway/approvals.py` | Approval lifecycle | Bot calls these via REST; do NOT duplicate logic |
| `services/api-gateway/chat.py` | Chat thread creation | Needs `thread_id` continuation support |
| `services/api-gateway/main.py` | FastAPI routes | Needs `GET /api/v1/approvals?status=pending` |
| `services/api-gateway/models.py` | Pydantic models | Needs `thread_id` on `ChatRequest` |
| `services/api-gateway/auth.py` | Entra token validation | Bot authenticates same way as all callers |
| `agents/shared/envelope.py` | Message envelope types | Bot uses `incident_handoff` message type |

## Appendix C: Decision Reconciliation

Decisions from 06-CONTEXT.md that need modification based on research:

| Decision | Status | Change Needed |
|----------|--------|---------------|
| D-01 (Separate TypeScript Container App) | Confirmed | None |
| D-02 (Bot calls api-gateway REST) | Confirmed | None |
| D-03 (No APIM) | Confirmed | None |
| D-04 (teams_notifier.py superseded) | Confirmed | None |
| D-05 (Typing indicator + full response) | Confirmed | None |
| D-06 (30s interim, 120s timeout) | Confirmed | None |
| D-07 (UPN from Teams activity) | Confirmed | None |
| **D-08 (Action.Http)** | **Needs revision** | **Must use Action.Execute** -- Action.Http not supported for bot-sent cards in Teams. Action.Execute provides better UX (in-place card update). |
| **D-09 (No in-place card edit)** | **Partially superseded** | **Action.Execute enables free in-place card updates** as part of the invoke response. Follow-up messages can still be sent additionally if desired, but the primary UX should be in-place card update. |
| D-10 (Action.OpenUrl for Investigate) | Confirmed | None |
| D-11 (Internal notify endpoint pattern) | Confirmed | None |
| D-12 (Incident-id-based thread lookup) | Confirmed | Api-gateway needs incident lookup endpoint or extend chat endpoint |
| D-13 (Free-form thread creation) | Confirmed | None |
| D-14 (Same thread_id cross-surface) | Confirmed | Api-gateway chat endpoint needs `thread_id` parameter |
| D-15 (setInterval escalation loop) | Confirmed | maxReplicas=1 to prevent duplicates |
| D-16 (15-min default, 2-min poll) | Confirmed | None |
| D-17 (Reminder card format) | Confirmed | Change Action.Http to Action.Execute in reminder card |
