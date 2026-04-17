# Messaging Agent

Domain specialist for Azure messaging services. Diagnoses health and operational issues across Azure Service Bus namespaces/queues/topics and Azure Event Hubs namespaces/consumer groups, correlating Azure Monitor metrics with queue depth and consumer lag before proposing any HITL-gated DLQ purge or configuration changes.

## Responsibilities
- List and inspect Service Bus namespaces, queues, topics, and subscriptions
- List and inspect Event Hubs namespaces and consumer groups
- Query Azure Monitor metrics: incoming/outgoing messages, active messages, DLQ depth, throttled requests, consumer lag
- Detect poison message accumulation and consumer group lag anomalies
- Propose (but never execute) DLQ purges or TTL/lock-duration configuration changes; gated by HITL approval (REMEDI-001)
- Produce diagnoses with confidence scores (0.0–1.0) (TRIAGE-004)

## Key Files
- `agent.py` — `ChatAgent` definition, system prompt, MCP tool allowlist (`monitor.query_metrics`, `monitor.query_logs`), and Foundry registration
- `tools.py` — `@ai_function` tools: Service Bus namespace/queue/topic list, Event Hub namespace/consumer group list, metrics query, DLQ purge proposal
- `requirements.txt` — agent-specific dependencies (`azure-mgmt-servicebus`, `azure-mgmt-eventhub`, `azure-mgmt-monitor`, `azure-monitor-query`)
- `Dockerfile` — container image built from `Dockerfile.base`
