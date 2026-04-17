# Teams Bot

TypeScript Teams bot built with the new Microsoft Teams SDK (`@microsoft/teams.js`). Delivers proactive alert notifications, supports two-way agent interaction via chat, and drives human-in-the-loop remediation approvals through Adaptive Cards.

## Tech Stack
- TypeScript / Node.js
- `@microsoft/teams.js` + `@microsoft/teams.ai` (new Teams SDK, GA)
- Adaptive Cards (approval flows)
- Vitest (unit tests)
- Docker (Container Apps deployment)

## Key Files / Directories

- `src/index.ts` — Bot entry point; registers HTTP handler and starts the Teams app
- `src/bot.ts` — Core bot class; handles activity routing (messages, card actions, installs)
- `src/config.ts` — Environment variable validation and typed config object
- `src/types.ts` — Shared TypeScript interfaces (alert payloads, approval state, etc.)
- `src/instrumentation.ts` — OpenTelemetry tracing setup
- `src/routes/` — Express route handlers (proactive alert delivery, health check)
- `src/services/` — Business logic: alert formatting, approval state, API Gateway client
- `src/cards/` — Adaptive Card JSON templates (alert notification, approval request, resolution summary)
- `src/__tests__/` — Vitest unit tests
- `appPackage/` — Teams app manifest and icons
- `Dockerfile` — Container image definition
- `package.json` — npm dependencies and scripts
- `vitest.config.ts` — Vitest configuration

## Running Locally

```bash
cd services/teams-bot
npm install
npm run dev
```

> Requires `BOT_ID`, `BOT_PASSWORD`, `TEAMS_CHANNEL_ID`, and `API_GATEWAY_URL` environment variables. Use [Teams Toolkit](https://marketplace.visualstudio.com/items?itemName=TeamsDevApp.ms-teams-vscode-extension) or `ngrok` for local tunnelling during development.
