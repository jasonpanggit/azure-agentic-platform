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
