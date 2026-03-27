"""Stub: Runbook RAG search tests (REMEDI-008)."""
import pytest


class TestRunbookRAG:
    """Tests for GET /api/v1/runbooks/search endpoint."""

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-03")
    def test_search_returns_top_3_results(self, client, pre_seeded_embeddings):
        """GET /api/v1/runbooks/search returns at most 3 results."""
        pass

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-03")
    def test_similarity_above_075_threshold(self, client, pre_seeded_embeddings):
        """All results have similarity score >= 0.75."""
        pass

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-03")
    def test_search_latency_under_500ms(self, client, pre_seeded_embeddings):
        """End-to-end runbook search completes in under 500ms."""
        pass

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-03")
    def test_domain_filter_applied(self, client, pre_seeded_embeddings):
        """domain=compute query returns only compute runbooks."""
        pass

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-03")
    def test_citation_includes_title_and_version(self, client, pre_seeded_embeddings):
        """Each result includes title and version fields."""
        pass
