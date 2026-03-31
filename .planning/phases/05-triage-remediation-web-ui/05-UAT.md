---
status: testing
phase: 05-triage-remediation-web-ui
source: [SUMMARY-05-00.md, SUMMARY-05-01.md, SUMMARY-05-02.md, SUMMARY-05-03.md, SUMMARY-05-04.md, SUMMARY-05-05.md]
started: 2026-03-30T23:12:00Z
updated: 2026-03-30T23:12:00Z
---

## Current Test

number: 1
name: Cold Start Smoke Test
expected: |
  Kill any running server/service. Clear ephemeral state (temp DBs, caches, lock files). Start the application from scratch (docker-compose up or equivalent). The API gateway boots without errors, DB migrations and seed data complete cleanly, and a basic health check or API call returns live data.
awaiting: user response

## Tests

### 1. Cold Start Smoke Test
expected: Kill any running server/service. Clear ephemeral state (temp DBs, caches, lock files). Start the application from scratch (docker-compose up or equivalent). The API gateway boots without errors, DB migrations and seed data complete cleanly, and a basic health check or API call returns live data.
result: [pending]

### 2. Unauthenticated user sees login prompt
expected: When visiting the app without an active Entra session, the user sees a login button (not the main shell). Clicking it triggers an MSAL PKCE redirect to the Microsoft login page.
result: [pending]

### 3. Desktop-only gate blocks narrow viewports
expected: When the browser window is narrower than 1200px, the app replaces the main content with a message indicating a desktop browser is required. Resizing above 1200px restores the full UI.
result: [pending]

### 4. Split-pane layout renders and persists
expected: After login, the shell shows a left chat panel (≈35% width) and a right dashboard panel (≈65% width). Dragging the divider to a new position and refreshing the page restores the same split ratio (persisted via localStorage).
result: [pending]

### 5. Chat input submits and shows thinking indicator
expected: Typing a message in the chat input and pressing Enter (or clicking Send) disables the input and displays a 'ThinkingIndicator' spinner (e.g., 'Agent is analyzing…') while waiting for the first streamed token.
result: [pending]

### 6. Streaming response renders token-by-token
expected: After submitting a chat message, agent response text appears incrementally in a chat bubble with a blinking cursor. Once streaming completes the cursor disappears and the full response is displayed.
result: [pending]

### 7. TraceTree shows collapsible tool calls
expected: Agent trace events appear below the response as a collapsed panel showing an event count summary. Clicking the panel expands a tree of tool-call nodes with type icons and status badges (green/orange/red). Clicking a node toggles a monospace JSON payload.
result: [pending]

### 8. SSE reconnect replays missed events
expected: When the SSE connection is dropped and re-established (e.g., briefly offline), the chat stream resumes from the last received sequence number without duplicate or missing tokens — the message text is complete and unbroken.
result: [pending]

### 9. POST /api/v1/chat returns 202
expected: A POST to /api/v1/chat with a valid Bearer token and a JSON body containing a message field returns HTTP 202 Accepted with a JSON body containing thread_id and status fields.
result: [pending]

### 10. Runbook search returns top-3 results
expected: A GET to /api/v1/runbooks/search?query=<text> returns a JSON array of up to 3 runbook objects, each containing id, title, domain, version, similarity (≥0.75), and content_excerpt fields.
result: [pending]

### 11. Runbook search domain filter works
expected: When GET /api/v1/runbooks/search is called with a domain=network query parameter, all returned runbooks have domain='network'. Results with a different domain are absent from the response.
result: [pending]

### 12. ProposalCard renders with countdown timer
expected: When the agent reaches an approval gate, a ProposalCard appears inline in the chat showing the proposal details, a live countdown timer (minutes:seconds remaining), and Approve/Reject buttons.
result: [pending]

### 13. Approve action triggers confirmation dialog
expected: Clicking the Approve button on a ProposalCard opens a Fluent UI dialog asking the user to confirm. Confirming POSTs to /api/proxy/approvals/{id}/approve and updates the card to show an 'approved' state badge.
result: [pending]

### 14. Reject action triggers confirmation dialog
expected: Clicking the Reject button on a ProposalCard opens a Fluent UI dialog asking the user to confirm. Confirming POSTs to /api/proxy/approvals/{id}/reject and updates the card to show a 'rejected' state badge.
result: [pending]

### 15. Expired approval returns 410 Gone
expected: Attempting to approve or reject an approval that has passed its 30-minute expiry returns HTTP 410 Gone. The ProposalCard in the UI updates to show an 'expired' state badge.
result: [pending]

### 16. Stale approval aborted state displayed
expected: If the underlying resource changes between proposal creation and execution, the ProposalCard switches to an 'aborted' state badge and surfaces the reason 'stale_approval' visibly to the operator.
result: [pending]

### 17. Rate limiter returns 429 on excess calls
expected: After exceeding the allowed number of remediation calls within a 60-second sliding window for the same agent+subscription pair, the API returns HTTP 429 Too Many Requests.
result: [pending]

### 18. Protected-tag resource returns 403
expected: Attempting to approve a remediation for a resource tagged with protected:true returns HTTP 403 Forbidden. The request is blocked before any change is applied.
result: [pending]

### 19. Alert feed displays incidents with severity badges
expected: The Dashboard panel's Alerts tab shows a table of incidents with Severity, Domain, Resource, Status, and Time columns. Sev0/Sev1 rows display a red 'danger' badge; Sev2/Sev3 rows display an orange 'warning' badge.
result: [pending]

### 20. Alert feed polls and refreshes every 5 seconds
expected: New incidents added to the backend appear in the Alert feed within ~5 seconds without any manual user action or page refresh.
result: [pending]

### 21. Alert filters narrow displayed incidents
expected: Selecting a severity (e.g., Sev1), domain (e.g., Network), or status (e.g., New) in the Alerts tab toolbar immediately re-queries and shows only matching incidents. Resetting to 'All' restores the full list.
result: [pending]

### 22. Audit log viewer shows agent actions
expected: The Dashboard panel's Audit tab shows a table of agent actions with Timestamp, Agent, Tool, Outcome, and Duration columns. Successful outcomes display a green badge; others display a red badge.
result: [pending]

### 23. Audit log filters by agent and action
expected: Selecting a specific agent from the Agent dropdown or typing in the action filter field on the Audit tab re-fetches and shows only matching audit entries. When no results match, the table shows 'No actions recorded'.
result: [pending]

### 24. GET /api/v1/incidents returns filtered list
expected: A GET to /api/v1/incidents?severity=Sev1&domain=network with a valid Bearer token returns a JSON array of IncidentSummary objects containing only Sev1 network incidents, ordered by created_at descending.
result: [pending]

### 25. GET /api/v1/audit returns audit entries
expected: A GET to /api/v1/audit?incident_id=<id> with a valid Bearer token returns a JSON array of AuditEntry objects (timestamp, agent, tool, outcome, duration_ms, properties) for that incident. An empty array is returned rather than an error when the Log Analytics workspace is unavailable.
result: [pending]

## Summary

total: 25
passed: 0
issues: 0
pending: 25
skipped: 0
blocked: 0

## Gaps

[none yet]
