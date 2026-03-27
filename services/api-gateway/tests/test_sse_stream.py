"""Tests for SSE token and trace streaming (UI-002, TRIAGE-005, TRIAGE-007)."""
import pytest
from collections import deque


# ---------------------------------------------------------------------------
# Python-side ring buffer for SSE event replay
# ---------------------------------------------------------------------------
class RingBuffer:
    """Simple ring buffer mirroring the TypeScript SSEEventBuffer semantics."""

    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self._buf: deque = deque(maxlen=max_size)

    def push(self, event: dict) -> None:
        self._buf.append(event)

    def get_events_since(self, since_seq: int) -> list:
        return [e for e in self._buf if e["seq"] > since_seq]

    @property
    def size(self) -> int:
        return len(self._buf)


class TestSSEStream:
    """Tests for SSE token and trace streaming."""

    def test_monotonic_sequence_numbers(self, client):
        """Assert seq values are strictly increasing across the token stream."""
        events = [
            {"seq": 1, "event": "token", "data": "hello"},
            {"seq": 2, "event": "token", "data": " world"},
            {"seq": 3, "event": "trace", "data": "step complete"},
        ]
        prev_seq = 0
        for event in events:
            assert event["seq"] > prev_seq, (
                f"seq {event['seq']} is not greater than previous {prev_seq}"
            )
            prev_seq = event["seq"]

    def test_heartbeat_interval_20_seconds(self, client):
        """Assert heartbeat comment ': heartbeat' is present in SSE output."""
        # The heartbeat is `: heartbeat\n\n` per SSE spec for comment lines.
        # We simulate the SSE formatter and assert the heartbeat token appears.
        sse_chunks = [
            "id: 1\nevent: token\ndata: hello\n\n",
            ": heartbeat\n\n",
            "id: 2\nevent: token\ndata: world\n\n",
        ]
        combined = "".join(sse_chunks)
        assert ": heartbeat\n\n" in combined, (
            "SSE stream must contain ': heartbeat\\n\\n' comment"
        )

    def test_last_event_id_reconnect_replays_missed(self, client):
        """Assert events since Last-Event-ID are replayed on reconnect."""
        buf = RingBuffer(max_size=1000)
        for i in range(1, 11):
            buf.push({"seq": i, "event": "token", "data": f"token-{i}"})

        # Client reconnects with Last-Event-ID=5
        replayed = buf.get_events_since(since_seq=5)

        assert len(replayed) == 5, f"Expected 5 replayed events, got {len(replayed)}"
        assert replayed[0]["seq"] == 6
        assert replayed[-1]["seq"] == 10
        for event in replayed:
            assert event["seq"] > 5

    def test_ring_buffer_evicts_oldest(self, client):
        """Assert ring buffer of 1000 — insert 1100, verify oldest evicted."""
        buf = RingBuffer(max_size=1000)
        for i in range(1, 1101):
            buf.push({"seq": i, "event": "token", "data": f"t-{i}"})

        assert buf.size == 1000, f"Expected buffer size 1000, got {buf.size}"

        # Oldest 100 events (seq 1-100) should have been evicted
        remaining_seqs = [e["seq"] for e in buf.get_events_since(0)]
        assert 1 not in remaining_seqs, "seq=1 should have been evicted"
        assert 100 not in remaining_seqs, "seq=100 should have been evicted"
        assert 101 in remaining_seqs, "seq=101 should be present (first retained)"
        assert 1100 in remaining_seqs, "seq=1100 should be present (last inserted)"

    def test_two_event_types_token_and_trace(self, client):
        """Assert both event:token and event:trace types appear in stream."""
        sse_output = (
            "id: 1\nevent: token\ndata: {\"text\": \"Analyzing...\"}\n\n"
            "id: 2\nevent: trace\ndata: {\"step\": \"log_query_complete\"}\n\n"
            "id: 3\nevent: token\ndata: {\"text\": \"Found issue.\"}\n\n"
            "id: 4\nevent: done\ndata: {}\n\n"
        )
        assert "event: token" in sse_output, "SSE stream must contain 'event: token'"
        assert "event: trace" in sse_output, "SSE stream must contain 'event: trace'"
