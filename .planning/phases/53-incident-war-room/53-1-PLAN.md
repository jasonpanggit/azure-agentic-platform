---
wave: 1
depends_on: []
files_modified:
  - services/api-gateway/war_room.py
  - services/api-gateway/main.py
  - terraform/modules/databases/cosmos.tf
  - terraform/modules/databases/outputs.tf
  - tests/api-gateway/test_war_room.py
autonomous: true
---

# Plan 53-1: War Room Backend — Cosmos Data Model, CRUD, SSE Push, Presence, Handoff

## Goal

Implement the complete war room backend: Cosmos `war_rooms` container (Terraform), `war_room.py` module with all CRUD helpers, five FastAPI endpoints (`POST /api/v1/incidents/{id}/war-room` create/join, `POST .../annotations` add annotation, `GET .../stream` SSE push to all participants, `POST .../heartbeat` presence keep-alive, `POST .../handoff` generate GPT-4o handoff summary), and ≥35 unit tests. This is fully independent of the frontend — the backend contract drives Wave 2 UI.

## Context

War rooms extend the existing incidents pattern. Cosmos `war_rooms` container follows the same ETag-optimistic-concurrency pattern as `approvals.py` and `remediation_audit`. The `IncidentWarRoom` document has `incident_id` as partition key (matches `incidents` container for fast joins). The SSE endpoint fans out annotation events to all connected participants — in-memory `asyncio.Queue` per `incident_id` (same server-scope singleton pattern used by the existing SSE buffer at `lib/sse-buffer.ts` on the frontend; here a Python `_WAR_ROOM_QUEUES` dict handles it). The handoff summary calls the Azure OpenAI GPT-4o deployment directly via `AzureOpenAI` client, reusing `FOUNDRY_ENDPOINT` and `AZURE_OPENAI_DEPLOYMENT` environment variables already set on the API gateway container.

<threat_model>
## Security Threat Assessment

**1. Participant identity**: `operator_id` is extracted from the Entra JWT (`sub` claim) by the existing `verify_token` dependency — no self-reported identity accepted in the request body. The gateway already enforces Entra auth (`API_GATEWAY_AUTH_MODE`).

**2. SSE fan-out queue isolation**: Each `incident_id` gets its own `asyncio.Queue`. Queues are never shared across incidents. Disconnected clients have their queues garbage-collected by the cleanup `finally` block in the stream generator.

**3. Annotation content**: Stored as plain text — no HTML rendering in the backend. Frontend is responsible for escaping. Max length enforced at `4096` chars via Pydantic field constraint.

**4. ETag concurrency on join**: The `join_war_room()` helper uses ETag-based conditional replace (`etag=record["_etag"]`) to prevent two simultaneous joins from creating duplicate participant entries — same pattern as `approvals.py`.

**5. Handoff summary GPT-4o call**: Passes war room context (hypothesis, open questions, pending approvals) as user content. No user-controlled system prompt injection. The system prompt is a hardcoded string. Response max_tokens capped at 1024 to bound cost.

**6. Presence heartbeat**: `POST .../heartbeat` updates `last_seen_at` timestamp on the participant's entry in `participants[]`. No mutation of other fields — only `last_seen_at`. Participants inactive >60s are considered offline for UI display only — not forcibly removed from the document.

**7. Cosmos `war_rooms` container**: Partition key `/incident_id` — all operations against a single incident are single-partition (fast, cheap). TTL = 7 days (war rooms are operational artefacts, not compliance records).
</threat_model>

---

## Tasks

### Task 1: Add `war_rooms` Cosmos container in Terraform

<read_first>
- `terraform/modules/databases/cosmos.tf` lines 55–145 — existing `incidents` and `sessions` container blocks; exact `azurerm_cosmosdb_sql_container` structure, `partition_key_paths`, `indexing_policy`, TTL pattern
- `terraform/modules/databases/outputs.tf` — existing `cosmos_*_container_name` output pattern to replicate for `war_rooms`
</read_first>

<action>
Add one new container resource block to `terraform/modules/databases/cosmos.tf`, after the `remediation_audit` container block:

```hcl
resource "azurerm_cosmosdb_sql_container" "war_rooms" {
  name                  = "war_rooms"
  resource_group_name   = var.resource_group_name
  account_name          = azurerm_cosmosdb_account.main.name
  database_name         = azurerm_cosmosdb_sql_database.main.name
  partition_key_paths   = ["/incident_id"]
  partition_key_version = 2
  default_ttl           = 604800 # 7 days — war rooms are operational artefacts

  indexing_policy {
    indexing_mode = "consistent"

    included_path { path = "/*" }
    excluded_path { path = "/annotations/*/content/?" }  # large text field — exclude from index
    excluded_path { path = "/_etag/?" }
  }
}
```

Add one new output to `terraform/modules/databases/outputs.tf` (after `cosmos_remediation_audit_container_name`):

```hcl
output "cosmos_war_rooms_container_name" {
  value       = azurerm_cosmosdb_sql_container.war_rooms.name
  description = "War rooms Cosmos container name"
}
```
</action>

<acceptance_criteria>
- `grep 'name.*=.*"war_rooms"' terraform/modules/databases/cosmos.tf` exits 0
- `grep 'partition_key_paths.*=.*\["/incident_id"\]' terraform/modules/databases/cosmos.tf` exits 0
- `grep 'default_ttl.*=.*604800' terraform/modules/databases/cosmos.tf` exits 0
- `grep 'cosmos_war_rooms_container_name' terraform/modules/databases/outputs.tf` exits 0
- `cd terraform && terraform fmt -check modules/databases/ && echo "fmt ok"` exits 0
</acceptance_criteria>

---

### Task 2: Create `services/api-gateway/war_room.py` — data model helpers

<read_first>
- `services/api-gateway/approvals.py` lines 1–70 — exact module header, `_get_approvals_container()` helper pattern, `CosmosClient` import, `CosmosResourceNotFoundError` import, `DefaultAzureCredential` fallback, `Optional[CosmosClient]` dependency pattern
- `services/api-gateway/approvals.py` lines 155–175 — `create_approval_record()` ETag pattern: `container.upsert_item(record)` first creation, `container.replace_item(item=doc["id"], body=updated, etag=etag, match_condition=MatchConditions.IfNotModified)` for updates
- `services/api-gateway/models.py` lines 1–50 — existing Pydantic model header pattern
</read_first>

<action>
Create `services/api-gateway/war_room.py` with the following complete implementation:

**Module header:**
```python
"""War Room — multi-operator collaborative incident investigation (Phase 53).

Provides Cosmos CRUD helpers for IncidentWarRoom documents and the in-memory
SSE fan-out queue registry for real-time annotation broadcast.

Document schema:
    {
        "id":              "<incident_id>",        # Cosmos item ID = incident_id
        "incident_id":     "<incident_id>",        # partition key
        "created_at":      "<ISO-8601>",
        "participants":    [
            {
                "operator_id":   "<entra-sub-claim>",
                "display_name":  "<str>",          # from JWT name claim, may be ""
                "role":          "lead|support",
                "joined_at":     "<ISO-8601>",
                "last_seen_at":  "<ISO-8601>",
            }
        ],
        "annotations":     [
            {
                "id":            "<uuid4>",
                "operator_id":   "<entra-sub-claim>",
                "display_name":  "<str>",
                "content":       "<str, max 4096 chars>",
                "trace_event_id": "<str|null>",    # pin to agent trace event, optional
                "created_at":    "<ISO-8601>",
            }
        ],
        "timeline":        [],                     # reserved for future agent events
        "handoff_summary": null,                   # filled by /handoff endpoint
        "_etag":           "<cosmos-etag>",
    }
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from azure.cosmos import ContainerProxy, CosmosClient, MatchConditions
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from azure.identity import DefaultAzureCredential

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory SSE fan-out queue registry
# ---------------------------------------------------------------------------
# Dict[incident_id, List[asyncio.Queue[str]]]
# Each connected SSE client has one queue. Annotation events are put() on all
# queues for the incident. The SSE stream generator get()s from its own queue.
# Queues are appended on connect and removed in the finally block on disconnect.
_WAR_ROOM_QUEUES: Dict[str, List[asyncio.Queue]] = {}
```

**`_get_war_rooms_container(cosmos_client)` helper:**
```python
def _get_war_rooms_container(
    cosmos_client: Optional[CosmosClient] = None,
) -> ContainerProxy:
    """Return the war_rooms Cosmos container proxy.

    Falls back to building a client from COSMOS_ENDPOINT env var when the
    shared singleton is not provided (e.g. in unit tests).
    """
    if cosmos_client is None:
        endpoint = os.environ.get("COSMOS_ENDPOINT", "")
        if not endpoint:
            raise RuntimeError("COSMOS_ENDPOINT not set and no cosmos_client provided")
        cosmos_client = CosmosClient(url=endpoint, credential=DefaultAzureCredential())

    database_name = os.environ.get("COSMOS_DATABASE", "aap")
    container_name = os.environ.get("COSMOS_WAR_ROOMS_CONTAINER", "war_rooms")
    return cosmos_client.get_database_client(database_name).get_container_client(container_name)
```

**`get_or_create_war_room(incident_id, operator_id, display_name, role, cosmos_client) -> dict`:**
```python
async def get_or_create_war_room(
    incident_id: str,
    operator_id: str,
    display_name: str,
    role: str,
    cosmos_client: Optional[CosmosClient] = None,
) -> dict:
    """Create war room if it does not exist, then add operator as participant.

    Uses ETag optimistic concurrency on the join so two simultaneous callers
    cannot create duplicate participant entries.

    Returns the updated war room document (without _etag, _rid, etc.).
    """
    container = _get_war_rooms_container(cosmos_client=cosmos_client)
    now = datetime.now(timezone.utc).isoformat()

    try:
        doc = container.read_item(item=incident_id, partition_key=incident_id)
    except CosmosResourceNotFoundError:
        # First join — create the war room document
        doc = {
            "id": incident_id,
            "incident_id": incident_id,
            "created_at": now,
            "participants": [],
            "annotations": [],
            "timeline": [],
            "handoff_summary": None,
        }
        doc = container.upsert_item(doc)
        logger.info("war_room: created | incident_id=%s", incident_id)

    # Check if operator is already a participant
    etag = doc.get("_etag", "")
    participants: list = doc.get("participants", [])
    existing = next((p for p in participants if p["operator_id"] == operator_id), None)

    if existing is None:
        new_participant = {
            "operator_id": operator_id,
            "display_name": display_name,
            "role": role if role in ("lead", "support") else "support",
            "joined_at": now,
            "last_seen_at": now,
        }
        # Immutable update — create new participants list
        updated_participants = [*participants, new_participant]
        updated = {**doc, "participants": updated_participants}
        # Remove Cosmos system properties before replace
        for k in ("_etag", "_rid", "_self", "_ts", "_attachments"):
            updated.pop(k, None)
        try:
            doc = container.replace_item(
                item=incident_id,
                body=updated,
                etag=etag,
                match_condition=MatchConditions.IfNotModified,
            )
        except Exception as exc:
            # ETag conflict — re-read and retry once (second join wins)
            logger.warning("war_room: join etag conflict | incident_id=%s error=%s", incident_id, exc)
            doc = container.read_item(item=incident_id, partition_key=incident_id)
        logger.info("war_room: participant joined | incident_id=%s operator_id=%s", incident_id, operator_id)
    else:
        logger.debug("war_room: participant already present | incident_id=%s operator_id=%s", incident_id, operator_id)

    return _strip_cosmos_fields(doc)
```

**`add_annotation(incident_id, operator_id, display_name, content, trace_event_id, cosmos_client) -> dict`:**
```python
async def add_annotation(
    incident_id: str,
    operator_id: str,
    display_name: str,
    content: str,
    trace_event_id: Optional[str],
    cosmos_client: Optional[CosmosClient] = None,
) -> dict:
    """Append an annotation to the war room timeline and broadcast via SSE queues.

    Returns the new annotation dict.
    """
    if len(content) > 4096:
        raise ValueError(f"Annotation content exceeds 4096 char limit: {len(content)} chars")

    container = _get_war_rooms_container(cosmos_client=cosmos_client)
    now = datetime.now(timezone.utc).isoformat()
    annotation_id = str(uuid.uuid4())

    annotation = {
        "id": annotation_id,
        "operator_id": operator_id,
        "display_name": display_name,
        "content": content,
        "trace_event_id": trace_event_id,
        "created_at": now,
    }

    # ETag-safe append with one retry
    for attempt in range(2):
        doc = container.read_item(item=incident_id, partition_key=incident_id)
        etag = doc.get("_etag", "")
        updated_annotations = [*doc.get("annotations", []), annotation]
        updated = {**doc, "annotations": updated_annotations}
        for k in ("_etag", "_rid", "_self", "_ts", "_attachments"):
            updated.pop(k, None)
        try:
            container.replace_item(
                item=incident_id,
                body=updated,
                etag=etag,
                match_condition=MatchConditions.IfNotModified,
            )
            break
        except Exception as exc:
            if attempt == 1:
                raise
            logger.warning("war_room: annotation etag conflict | attempt=%d error=%s", attempt, exc)

    logger.info("war_room: annotation added | incident_id=%s annotation_id=%s", incident_id, annotation_id)

    # Broadcast to all connected SSE clients for this incident
    _broadcast_annotation(incident_id, annotation)

    return annotation
```

**`update_presence(incident_id, operator_id, cosmos_client) -> None`:**
```python
async def update_presence(
    incident_id: str,
    operator_id: str,
    cosmos_client: Optional[CosmosClient] = None,
) -> None:
    """Update last_seen_at for an operator in the war room participants list."""
    container = _get_war_rooms_container(cosmos_client=cosmos_client)
    now = datetime.now(timezone.utc).isoformat()

    for attempt in range(2):
        try:
            doc = container.read_item(item=incident_id, partition_key=incident_id)
        except CosmosResourceNotFoundError:
            return  # War room doesn't exist yet — presence update is a no-op

        etag = doc.get("_etag", "")
        participants = doc.get("participants", [])
        # Immutable update of last_seen_at for matching operator
        updated_participants = [
            {**p, "last_seen_at": now} if p["operator_id"] == operator_id else p
            for p in participants
        ]
        updated = {**doc, "participants": updated_participants}
        for k in ("_etag", "_rid", "_self", "_ts", "_attachments"):
            updated.pop(k, None)
        try:
            container.replace_item(
                item=incident_id,
                body=updated,
                etag=etag,
                match_condition=MatchConditions.IfNotModified,
            )
            return
        except Exception as exc:
            if attempt == 1:
                logger.warning("war_room: presence update failed after retry | error=%s", exc)
                return
```

**`generate_handoff_summary(incident_id, cosmos_client) -> str`:**
```python
async def generate_handoff_summary(
    incident_id: str,
    cosmos_client: Optional[CosmosClient] = None,
) -> str:
    """Generate a GPT-4o shift-handoff summary for the war room.

    Reads the current war room state (annotations, participants) and calls
    Azure OpenAI GPT-4o to produce a structured handoff document covering:
    - Current hypothesis
    - Open questions
    - Pending approvals
    - Recommended next steps

    Returns the generated summary string. Also persists it to the war room doc.
    Raises RuntimeError if FOUNDRY_ENDPOINT or AZURE_OPENAI_DEPLOYMENT are unset.
    """
    try:
        from openai import AzureOpenAI
    except ImportError as exc:
        raise RuntimeError("openai package not installed") from exc

    endpoint = os.environ.get("FOUNDRY_ENDPOINT") or os.environ.get("AZURE_OPENAI_ENDPOINT", "")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
    if not endpoint:
        raise RuntimeError("FOUNDRY_ENDPOINT or AZURE_OPENAI_ENDPOINT not set")

    container = _get_war_rooms_container(cosmos_client=cosmos_client)
    doc = container.read_item(item=incident_id, partition_key=incident_id)

    annotations = doc.get("annotations", [])
    participants = doc.get("participants", [])
    annotation_text = "\n".join(
        f"[{a['display_name'] or a['operator_id']} @ {a['created_at']}]: {a['content']}"
        for a in annotations
    )
    participant_names = ", ".join(
        p.get("display_name") or p["operator_id"] for p in participants
    )

    system_prompt = (
        "You are an AIOps incident coordinator writing a shift-handoff summary. "
        "Be concise and structured. Focus on what the next shift needs to know immediately."
    )
    user_content = f"""Incident ID: {incident_id}
Active operators: {participant_names}

Investigation notes (chronological):
{annotation_text or "(no annotations yet)"}

Write a structured handoff summary with these sections:
1. Current Hypothesis — one paragraph, what we think is happening and why
2. Open Questions — bullet list, what is still unknown
3. Pending Approvals — bullet list, any HITL approvals outstanding (if none, say "None")
4. Recommended Next Steps — ordered list of actions for the incoming shift
"""

    credential = DefaultAzureCredential()
    token = credential.get_token("https://cognitiveservices.azure.com/.default")
    client = AzureOpenAI(
        azure_endpoint=endpoint,
        api_key=token.token,
        api_version="2024-10-21",
    )

    response = client.chat.completions.create(
        model=deployment,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        max_tokens=1024,
        temperature=0.2,
    )
    summary = response.choices[0].message.content or ""

    # Persist summary to war room doc
    etag = doc.get("_etag", "")
    updated = {**doc, "handoff_summary": summary}
    for k in ("_etag", "_rid", "_self", "_ts", "_attachments"):
        updated.pop(k, None)
    try:
        container.replace_item(
            item=incident_id,
            body=updated,
            etag=etag,
            match_condition=MatchConditions.IfNotModified,
        )
    except Exception as exc:
        logger.warning("war_room: failed to persist handoff summary | error=%s", exc)

    logger.info("war_room: handoff summary generated | incident_id=%s length=%d", incident_id, len(summary))
    return summary
```

**SSE queue helpers:**
```python
def _broadcast_annotation(incident_id: str, annotation: dict) -> None:
    """Put annotation event on all active SSE queues for this incident."""
    import json
    queues = _WAR_ROOM_QUEUES.get(incident_id, [])
    payload = json.dumps({"type": "annotation", "annotation": annotation})
    for q in queues:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            logger.warning("war_room: SSE queue full — dropping event for incident_id=%s", incident_id)


def register_sse_queue(incident_id: str, queue: asyncio.Queue) -> None:
    """Register an SSE client queue for an incident."""
    if incident_id not in _WAR_ROOM_QUEUES:
        _WAR_ROOM_QUEUES[incident_id] = []
    _WAR_ROOM_QUEUES[incident_id].append(queue)
    logger.debug("war_room: SSE queue registered | incident_id=%s total=%d", incident_id, len(_WAR_ROOM_QUEUES[incident_id]))


def deregister_sse_queue(incident_id: str, queue: asyncio.Queue) -> None:
    """Remove a disconnected SSE client queue."""
    queues = _WAR_ROOM_QUEUES.get(incident_id, [])
    try:
        queues.remove(queue)
    except ValueError:
        pass
    if not queues:
        _WAR_ROOM_QUEUES.pop(incident_id, None)
    logger.debug("war_room: SSE queue deregistered | incident_id=%s remaining=%d", incident_id, len(queues))


def _strip_cosmos_fields(doc: dict) -> dict:
    """Return doc without Cosmos system fields (_etag, _rid, _self, _ts, _attachments)."""
    return {k: v for k, v in doc.items() if not k.startswith("_")}
```
</action>

<acceptance_criteria>
- File `services/api-gateway/war_room.py` exists
- `grep "def _get_war_rooms_container" services/api-gateway/war_room.py` exits 0
- `grep "async def get_or_create_war_room" services/api-gateway/war_room.py` exits 0
- `grep "async def add_annotation" services/api-gateway/war_room.py` exits 0
- `grep "async def update_presence" services/api-gateway/war_room.py` exits 0
- `grep "async def generate_handoff_summary" services/api-gateway/war_room.py` exits 0
- `grep "_WAR_ROOM_QUEUES" services/api-gateway/war_room.py` exits 0
- `grep "register_sse_queue" services/api-gateway/war_room.py` exits 0
- `grep "deregister_sse_queue" services/api-gateway/war_room.py` exits 0
- `grep "MatchConditions.IfNotModified" services/api-gateway/war_room.py` exits 0
- `grep "4096" services/api-gateway/war_room.py` exits 0
- `grep "max_tokens=1024" services/api-gateway/war_room.py` exits 0
- `grep "_strip_cosmos_fields" services/api-gateway/war_room.py` exits 0
</acceptance_criteria>

---

### Task 3: Add war room FastAPI endpoints in `services/api-gateway/main.py`

<read_first>
- `services/api-gateway/main.py` lines 550–580 — existing `app.include_router()` block to find correct insertion point for inline war room routes (war room routes are thin enough to be inline, not a separate module — follow the `chat.py` pattern where POST `/api/v1/chat` is registered inline in `main.py`)
- `services/api-gateway/approvals.py` lines 60–130 — `verify_token` dependency usage, `get_optional_cosmos_client` pattern, `Optional[CosmosClient]` in endpoint signature
- `services/api-gateway/chat.py` lines 1–30 — `ChatRequest` model pattern for inline request models
</read_first>

<action>
Add 5 new endpoint handlers and their imports to `services/api-gateway/main.py`.

**Import additions** (after existing war_room-unrelated imports, near other service imports):
```python
from services.api_gateway.war_room import (
    get_or_create_war_room,
    add_annotation,
    update_presence,
    generate_handoff_summary,
    register_sse_queue,
    deregister_sse_queue,
)
```

**Pydantic request models** (add near other inline models in main.py, e.g. after `ChatRequest`):
```python
class WarRoomJoinRequest(BaseModel):
    display_name: str = ""
    role: str = "support"  # "lead" or "support"


class AnnotationRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=4096)
    trace_event_id: Optional[str] = None
    display_name: str = ""
```

**Endpoint 1 — `POST /api/v1/incidents/{incident_id}/war-room`** (create/join):
```python
@app.post("/api/v1/incidents/{incident_id}/war-room")
async def create_or_join_war_room(
    incident_id: str,
    body: WarRoomJoinRequest,
    token_claims: dict = Depends(verify_token),
    cosmos_client: Optional[CosmosClient] = Depends(get_optional_cosmos_client),
):
    operator_id: str = token_claims.get("sub", "anonymous")
    display_name: str = body.display_name or token_claims.get("name", "")
    war_room = await get_or_create_war_room(
        incident_id=incident_id,
        operator_id=operator_id,
        display_name=display_name,
        role=body.role,
        cosmos_client=cosmos_client,
    )
    return {"ok": True, "war_room": war_room}
```

**Endpoint 2 — `POST /api/v1/incidents/{incident_id}/war-room/annotations`**:
```python
@app.post("/api/v1/incidents/{incident_id}/war-room/annotations")
async def post_annotation(
    incident_id: str,
    body: AnnotationRequest,
    token_claims: dict = Depends(verify_token),
    cosmos_client: Optional[CosmosClient] = Depends(get_optional_cosmos_client),
):
    operator_id: str = token_claims.get("sub", "anonymous")
    display_name: str = body.display_name or token_claims.get("name", "")
    annotation = await add_annotation(
        incident_id=incident_id,
        operator_id=operator_id,
        display_name=display_name,
        content=body.content,
        trace_event_id=body.trace_event_id,
        cosmos_client=cosmos_client,
    )
    return {"ok": True, "annotation": annotation}
```

**Endpoint 3 — `GET /api/v1/incidents/{incident_id}/war-room/stream`** (SSE push):
```python
@app.get("/api/v1/incidents/{incident_id}/war-room/stream")
async def war_room_sse_stream(
    incident_id: str,
    token_claims: dict = Depends(verify_token),
):
    """SSE endpoint — pushes annotation events to all connected participants."""
    import asyncio
    import json
    from fastapi.responses import StreamingResponse

    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    register_sse_queue(incident_id, queue)

    async def event_generator():
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=20.0)
                    yield f"event: annotation\ndata: {payload}\n\n"
                except asyncio.TimeoutError:
                    # 20-second heartbeat comment to prevent Container Apps 240s timeout
                    yield ": heartbeat\n\n"
        finally:
            deregister_sse_queue(incident_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
```

**Endpoint 4 — `POST /api/v1/incidents/{incident_id}/war-room/heartbeat`** (presence):
```python
@app.post("/api/v1/incidents/{incident_id}/war-room/heartbeat")
async def war_room_heartbeat(
    incident_id: str,
    token_claims: dict = Depends(verify_token),
    cosmos_client: Optional[CosmosClient] = Depends(get_optional_cosmos_client),
):
    operator_id: str = token_claims.get("sub", "anonymous")
    await update_presence(
        incident_id=incident_id,
        operator_id=operator_id,
        cosmos_client=cosmos_client,
    )
    return {"ok": True}
```

**Endpoint 5 — `POST /api/v1/incidents/{incident_id}/war-room/handoff`** (GPT-4o summary):
```python
@app.post("/api/v1/incidents/{incident_id}/war-room/handoff")
async def generate_war_room_handoff(
    incident_id: str,
    token_claims: dict = Depends(verify_token),
    cosmos_client: Optional[CosmosClient] = Depends(get_optional_cosmos_client),
):
    try:
        summary = await generate_handoff_summary(
            incident_id=incident_id,
            cosmos_client=cosmos_client,
        )
        return {"ok": True, "summary": summary}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
```
</action>

<acceptance_criteria>
- `grep "from services.api_gateway.war_room import" services/api-gateway/main.py` exits 0
- `grep "class WarRoomJoinRequest" services/api-gateway/main.py` exits 0
- `grep "class AnnotationRequest" services/api-gateway/main.py` exits 0
- `grep '"/api/v1/incidents/{incident_id}/war-room"' services/api-gateway/main.py` exits 0
- `grep '"/api/v1/incidents/{incident_id}/war-room/annotations"' services/api-gateway/main.py` exits 0
- `grep '"/api/v1/incidents/{incident_id}/war-room/stream"' services/api-gateway/main.py` exits 0
- `grep '"/api/v1/incidents/{incident_id}/war-room/heartbeat"' services/api-gateway/main.py` exits 0
- `grep '"/api/v1/incidents/{incident_id}/war-room/handoff"' services/api-gateway/main.py` exits 0
- `grep "text/event-stream" services/api-gateway/main.py` exits 0
- `grep "StreamingResponse" services/api-gateway/main.py` exits 0
</acceptance_criteria>

---

### Task 4: Create `tests/api-gateway/test_war_room.py`

<read_first>
- `tests/api-gateway/test_finops_endpoints.py` — exact `TestClient` + `mock.patch` pattern; `app = FastAPI(); app.include_router(router); client = TestClient(app, raise_server_exceptions=False)`
- `services/api-gateway/approvals.py` — `test_approvals_lifecycle.py` or closest test for Cosmos mock pattern: `MagicMock()` for `ContainerProxy`, `CosmosResourceNotFoundError` raise pattern
- `services/api-gateway/war_room.py` (just written) — exact function signatures and return shapes
</read_first>

<action>
Create `tests/api-gateway/test_war_room.py` with ≥35 tests across 8 test classes.

**Imports and helpers:**
```python
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from azure.cosmos.exceptions import CosmosResourceNotFoundError

from services.api_gateway.war_room import (
    get_or_create_war_room,
    add_annotation,
    update_presence,
    generate_handoff_summary,
    register_sse_queue,
    deregister_sse_queue,
    _broadcast_annotation,
    _WAR_ROOM_QUEUES,
    _strip_cosmos_fields,
)


def _make_war_room_doc(incident_id="inc-001", participants=None, annotations=None):
    return {
        "id": incident_id,
        "incident_id": incident_id,
        "created_at": "2026-04-14T10:00:00+00:00",
        "participants": participants or [],
        "annotations": annotations or [],
        "timeline": [],
        "handoff_summary": None,
        "_etag": '"etag-123"',
        "_rid": "abc",
    }


def _make_container_mock(existing_doc=None):
    """Return a MagicMock ContainerProxy with read_item and replace_item configured."""
    m = MagicMock()
    if existing_doc is None:
        m.read_item.side_effect = CosmosResourceNotFoundError(message="Not found", response=MagicMock())
    else:
        m.read_item.return_value = existing_doc
    m.upsert_item.side_effect = lambda doc: {**doc, "_etag": '"etag-new"'}
    m.replace_item.side_effect = lambda item, body, etag=None, match_condition=None: {**body, "_etag": '"etag-updated"'}
    return m
```

**`TestStripCosmosFields` (3 tests):**
- `test_strips_etag` — `assert "_etag" not in _strip_cosmos_fields({"id": "x", "_etag": "y"})`
- `test_strips_all_system_fields` — input has `_etag`, `_rid`, `_self`, `_ts`, `_attachments`; assert none present in output
- `test_preserves_data_fields` — `incident_id`, `participants`, `annotations` preserved intact

**`TestGetOrCreateWarRoom` (6 tests):**
Patch `services.api_gateway.war_room._get_war_rooms_container`:
- `test_creates_new_war_room_when_not_exists` — container mock raises `CosmosResourceNotFoundError`; `upsert_item` called once; assert `result["incident_id"] == "inc-001"`
- `test_adds_participant_on_create` — fresh doc returned; assert `len(result["participants"]) == 1`, `result["participants"][0]["operator_id"] == "user-123"`, `result["participants"][0]["role"] == "support"`
- `test_joins_existing_war_room` — container returns existing doc with 1 participant; call with different operator; assert `len(result["participants"]) == 2`
- `test_does_not_duplicate_existing_participant` — existing doc has participant `user-123`; call join with same `operator_id`; assert `len(result["participants"]) == 1` (no duplicate)
- `test_role_defaults_to_support_for_invalid_role` — call with `role="admin"` (not valid); assert `result["participants"][0]["role"] == "support"`
- `test_returns_dict_without_cosmos_system_fields` — assert `"_etag" not in result`, `"_rid" not in result`

**`TestAddAnnotation` (7 tests):**
Patch `services.api_gateway.war_room._get_war_rooms_container`:
- `test_adds_annotation_to_existing_war_room` — mock returns existing doc; call `add_annotation`; assert `result["content"] == "my note"`, `result["operator_id"] == "user-123"`, `"id" in result`, `"created_at" in result`
- `test_annotation_id_is_uuid4` — assert `result["id"]` is a valid UUID string (36 chars with dashes)
- `test_annotation_with_trace_event_id` — call with `trace_event_id="trace-abc"`; assert `result["trace_event_id"] == "trace-abc"`
- `test_annotation_without_trace_event_id` — call with `trace_event_id=None`; assert `result["trace_event_id"] is None`
- `test_content_max_4096_chars_raises` — call with `content="x" * 4097`; assert `ValueError` raised
- `test_content_exactly_4096_chars_succeeds` — call with `content="x" * 4096`; assert returns without error
- `test_broadcasts_to_sse_queues` — register a `asyncio.Queue()` for `incident_id`; call `add_annotation`; assert `not q.empty()`

**`TestUpdatePresence` (4 tests):**
- `test_updates_last_seen_at` — mock returns doc with one participant; `replace_item` called once; assert last participant `last_seen_at` is updated
- `test_noop_when_war_room_not_exists` — container raises `CosmosResourceNotFoundError`; assert no exception raised, returns `None`
- `test_noop_when_operator_not_in_participants` — doc has participant `user-456`; call with `operator_id="user-123"` (different); assert `replace_item` still called (all participants mapped)
- `test_immutable_update` — verify `replace_item` is called with a NEW dict (not mutated in-place); check that `replace_item` was called with `match_condition` argument set

**`TestBroadcastAnnotation` (3 tests):**
- `test_broadcasts_to_all_queues` — register 3 queues; broadcast; assert all 3 have exactly 1 item
- `test_noop_for_incident_with_no_queues` — broadcast with no registered queues; assert no exception
- `test_full_queue_does_not_raise` — register queue with `maxsize=1`; put one item to fill it; broadcast again; assert no exception (QueueFull swallowed)

**`TestRegisterDeregisterQueues` (4 tests):**
- `test_register_creates_list_for_new_incident` — register on `"inc-new"` (not in `_WAR_ROOM_QUEUES`); assert `"inc-new" in _WAR_ROOM_QUEUES`, list has 1 entry
- `test_register_appends_to_existing` — register twice; assert list has 2 entries
- `test_deregister_removes_queue` — register then deregister; assert queue not in list
- `test_deregister_removes_empty_incident_key` — register 1 queue then deregister it; assert incident key removed from dict

**`TestHandoffSummary` (5 tests):**
Patch `services.api_gateway.war_room._get_war_rooms_container`, `services.api_gateway.war_room.DefaultAzureCredential`, `openai.AzureOpenAI`:
- `test_returns_summary_string` — mock `client.chat.completions.create` returns response with `choices[0].message.content = "Summary: hypothesis..."`; assert return value equals `"Summary: hypothesis..."`
- `test_persists_summary_to_cosmos` — assert `container.replace_item` called with body containing `"handoff_summary": "Summary: hypothesis..."`
- `test_raises_runtime_error_when_endpoint_missing` — patch `os.environ.get` to return `""` for `FOUNDRY_ENDPOINT`; assert `RuntimeError` raised with `"FOUNDRY_ENDPOINT"` in message
- `test_includes_annotations_in_prompt` — capture the `messages` arg to `create()`; assert annotation content appears in the user message content string
- `test_raises_runtime_error_when_openai_not_installed` — patch `builtins.__import__` to raise `ImportError` for `openai`; assert `RuntimeError` raised

**`TestSseStream` (3 tests):**
- `test_event_generator_yields_annotation_event` — register queue; put a payload; consume from generator; assert yielded string contains `"event: annotation"`
- `test_event_generator_yields_heartbeat_on_timeout` — queue empty; run generator one tick with short timeout override; assert yielded string starts with `: heartbeat`
- `test_deregisters_queue_on_generator_exit` — run generator and `.aclose()` it immediately; assert incident key removed from `_WAR_ROOM_QUEUES`
</action>

<acceptance_criteria>
- File `tests/api-gateway/test_war_room.py` exists
- `grep -c "def test_" tests/api-gateway/test_war_room.py` outputs a number >= 35
- `grep "class TestGetOrCreateWarRoom" tests/api-gateway/test_war_room.py` exits 0
- `grep "class TestAddAnnotation" tests/api-gateway/test_war_room.py` exits 0
- `grep "class TestUpdatePresence" tests/api-gateway/test_war_room.py` exits 0
- `grep "class TestHandoffSummary" tests/api-gateway/test_war_room.py` exits 0
- `grep "class TestSseStream" tests/api-gateway/test_war_room.py` exits 0
- `grep "class TestBroadcastAnnotation" tests/api-gateway/test_war_room.py` exits 0
- `grep "class TestRegisterDeregisterQueues" tests/api-gateway/test_war_room.py` exits 0
- `grep "4097" tests/api-gateway/test_war_room.py` exits 0
- `grep "CosmosResourceNotFoundError" tests/api-gateway/test_war_room.py` exits 0
- `python -m pytest tests/api-gateway/test_war_room.py -v --tb=short` exits 0 with all tests passing
</acceptance_criteria>

---

## Verification

```bash
# 1. Terraform fmt passes
cd terraform && terraform fmt -check modules/databases/

# 2. War room module imports cleanly
python -c "
from services.api_gateway.war_room import (
    get_or_create_war_room, add_annotation, update_presence,
    generate_handoff_summary, register_sse_queue, deregister_sse_queue
)
print('OK: all war_room exports importable')
"

# 3. Main.py imports without error
python -c "from services.api_gateway.main import app; print('OK: main.py imports')"

# 4. All 5 war room endpoints registered
python -c "
from services.api_gateway.main import app
routes = [r.path for r in app.routes]
wr_routes = [r for r in routes if 'war-room' in r]
assert len(wr_routes) == 5, f'Expected 5 war-room routes, got {len(wr_routes)}: {wr_routes}'
print('OK: all 5 war-room endpoints registered')
"

# 5. All tests pass
python -m pytest tests/api-gateway/test_war_room.py -v --tb=short
```

## must_haves

- [ ] `terraform/modules/databases/cosmos.tf` has `war_rooms` container with `partition_key_paths = ["/incident_id"]` and `default_ttl = 604800`
- [ ] `terraform/modules/databases/outputs.tf` has `cosmos_war_rooms_container_name` output
- [ ] `terraform fmt -check modules/databases/` passes
- [ ] `services/api-gateway/war_room.py` exists with all 5 async helpers: `get_or_create_war_room`, `add_annotation`, `update_presence`, `generate_handoff_summary`, and SSE queue helpers
- [ ] All document mutations use ETag `MatchConditions.IfNotModified` (immutable update pattern — no in-place mutation)
- [ ] Annotation content validated ≤4096 chars in `add_annotation` (`ValueError` on violation)
- [ ] GPT-4o call in `generate_handoff_summary` has `max_tokens=1024` and `temperature=0.2`
- [ ] All 5 FastAPI endpoints registered in `main.py` under `/api/v1/incidents/{incident_id}/war-room/*`
- [ ] SSE endpoint (`/war-room/stream`) uses `StreamingResponse` with `text/event-stream` + 20s heartbeat comment
- [ ] `tests/api-gateway/test_war_room.py` has ≥35 tests all passing
