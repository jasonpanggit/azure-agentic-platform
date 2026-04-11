"""Tests for agents/shared/sop_store.py — Foundry vector store provisioning."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


class TestProvisionSopVectorStore:
    """Verify provision_sop_vector_store creates vector store and uploads files."""

    def _make_project_mock(self):
        mock_project = MagicMock()
        mock_openai = MagicMock()
        mock_vs = MagicMock()
        mock_vs.id = "vs_test_123"
        mock_openai.vector_stores.create.return_value = mock_vs
        mock_openai.vector_stores.files.upload_and_poll.return_value = MagicMock()
        mock_project.get_openai_client.return_value = mock_openai
        return mock_project, mock_openai, mock_vs

    def test_creates_vector_store_with_name(self, tmp_path):
        sop_file = tmp_path / "vm-high-cpu.md"
        sop_file.write_text("# test SOP")

        mock_project, mock_openai, _mock_vs = self._make_project_mock()

        from agents.shared.sop_store import provision_sop_vector_store

        provision_sop_vector_store(mock_project, [sop_file])

        mock_openai.vector_stores.create.assert_called_once_with(name="aap-sops-v1")

    def test_returns_vector_store_id(self, tmp_path):
        sop_file = tmp_path / "test.md"
        sop_file.write_text("# test")

        mock_project, _mock_openai, _mock_vs = self._make_project_mock()

        from agents.shared.sop_store import provision_sop_vector_store

        result = provision_sop_vector_store(mock_project, [sop_file])
        assert result == "vs_test_123"

    def test_uploads_each_sop_file(self, tmp_path):
        sop1 = tmp_path / "vm-high-cpu.md"
        sop2 = tmp_path / "vm-memory.md"
        sop1.write_text("# SOP 1")
        sop2.write_text("# SOP 2")

        mock_project, mock_openai, _mock_vs = self._make_project_mock()

        from agents.shared.sop_store import provision_sop_vector_store

        provision_sop_vector_store(mock_project, [sop1, sop2])

        assert mock_openai.vector_stores.files.upload_and_poll.call_count == 2

    def test_upload_passes_correct_vector_store_id(self, tmp_path):
        sop_file = tmp_path / "vm-high-cpu.md"
        sop_file.write_text("# test")

        mock_project, mock_openai, _mock_vs = self._make_project_mock()

        from agents.shared.sop_store import provision_sop_vector_store

        provision_sop_vector_store(mock_project, [sop_file])

        call_kwargs = mock_openai.vector_stores.files.upload_and_poll.call_args
        assert call_kwargs.kwargs.get("vector_store_id") == "vs_test_123"

    def test_upload_passes_filename(self, tmp_path):
        sop_file = tmp_path / "vm-high-cpu.md"
        sop_file.write_text("# test")

        mock_project, mock_openai, _mock_vs = self._make_project_mock()

        from agents.shared.sop_store import provision_sop_vector_store

        provision_sop_vector_store(mock_project, [sop_file])

        call_kwargs = mock_openai.vector_stores.files.upload_and_poll.call_args
        assert call_kwargs.kwargs.get("filename") == "vm-high-cpu.md"

    def test_empty_file_list_creates_empty_store(self):
        mock_project, mock_openai, _mock_vs = self._make_project_mock()

        from agents.shared.sop_store import provision_sop_vector_store

        result = provision_sop_vector_store(mock_project, [])
        mock_openai.vector_stores.create.assert_called_once()
        mock_openai.vector_stores.files.upload_and_poll.assert_not_called()
        assert result == "vs_test_123"
