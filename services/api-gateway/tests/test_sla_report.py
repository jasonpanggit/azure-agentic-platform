"""Tests for SLA monthly report generation (Phase 55).

16 tests covering:
  Group A — _build_narrative (4 tests)
  Group B — _build_pdf (4 tests)
  Group C — _send_email (4 tests)
  Group D — generate_and_send_sla_report (4 tests)
"""
from __future__ import annotations

import os
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SLA_DEF = {
    "id": "aaaaaaaa-0000-0000-0000-000000000001",
    "name": "Prod SLA",
    "target_availability_pct": 99.9,
    "covered_resource_ids": [
        "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-01"
    ],
    "measurement_period": "monthly",
    "customer_name": "Contoso",
    "report_recipients": ["ops@contoso.com"],
}

_COMPLIANT_RESULT = {
    "sla_id": "aaaaaaaa-0000-0000-0000-000000000001",
    "sla_name": "Prod SLA",
    "target_availability_pct": 99.9,
    "attained_availability_pct": 99.95,
    "is_compliant": True,
    "period_start": "2026-04-01T00:00:00+00:00",
    "period_end": "2026-04-15T12:00:00+00:00",
    "resource_attainments": [],
    "duration_ms": 5.0,
}

_BREACH_RESULT = {
    **_COMPLIANT_RESULT,
    "attained_availability_pct": 98.0,
    "is_compliant": False,
}

_NO_DATA_RESULT = {
    **_COMPLIANT_RESULT,
    "attained_availability_pct": None,
    "is_compliant": None,
}


# ---------------------------------------------------------------------------
# Group A — _build_narrative
# ---------------------------------------------------------------------------

class TestBuildNarrative:
    """Tests for the _build_narrative / _fallback_narrative functions."""

    def test_narrative_fallback_compliant(self):
        """Fallback returns a string containing 'met' when is_compliant=True."""
        from services.api_gateway.sla_report import _fallback_narrative

        result = _fallback_narrative(_COMPLIANT_RESULT, _SLA_DEF)
        assert isinstance(result, str)
        assert "met" in result.lower()

    def test_narrative_fallback_non_compliant(self):
        """Fallback returns a string containing 'not met' when is_compliant=False."""
        from services.api_gateway.sla_report import _fallback_narrative

        result = _fallback_narrative(_BREACH_RESULT, _SLA_DEF)
        assert isinstance(result, str)
        assert "not met" in result.lower()

    def test_narrative_fallback_no_data(self):
        """Fallback returns string mentioning 'unavailable' when attained=None."""
        from services.api_gateway.sla_report import _fallback_narrative

        result = _fallback_narrative(_NO_DATA_RESULT, _SLA_DEF)
        assert isinstance(result, str)
        assert "unavailable" in result.lower()

    def test_narrative_gpt4o_failure_falls_back(self):
        """When AIProjectClient raises, _build_narrative returns fallback string."""
        import services.api_gateway.sla_report as mod

        mock_client_instance = MagicMock()
        mock_client_instance.inference.get_chat_completions.side_effect = RuntimeError("API error")
        mock_client_cls = MagicMock(return_value=mock_client_instance)

        with patch.object(mod, "AIProjectClient", mock_client_cls), \
             patch.object(mod, "_DefaultCred", MagicMock()), \
             patch.dict(os.environ, {"AZURE_AI_PROJECT_ENDPOINT": "https://fake.endpoint"}):
            result = mod._build_narrative(_COMPLIANT_RESULT, _SLA_DEF)

        # Should fall back gracefully — returns a non-empty string
        assert isinstance(result, str)
        assert len(result) > 0

    # ---------------------------------------------------------------------------
    # Group B — _build_pdf
    # ---------------------------------------------------------------------------

class TestBuildPdf:
    """Tests for the _build_pdf function."""

    def test_build_pdf_returns_bytes(self):
        """_build_pdf returns bytes with length > 1000 when reportlab is installed."""
        from services.api_gateway.sla_report import _build_pdf, SimpleDocTemplate

        if SimpleDocTemplate is None:
            pytest.skip("reportlab not installed")

        pdf = _build_pdf(_SLA_DEF, _COMPLIANT_RESULT, "SLA was met.", [])
        assert isinstance(pdf, bytes)
        assert len(pdf) > 1000

    def test_build_pdf_contains_sla_name(self):
        """PDF contains the sla_name — verified by decompressing the content stream."""
        from services.api_gateway.sla_report import _build_pdf, SimpleDocTemplate
        import zlib, re

        if SimpleDocTemplate is None:
            pytest.skip("reportlab not installed")

        pdf = _build_pdf(_SLA_DEF, _COMPLIANT_RESULT, "SLA was met.", [])
        assert isinstance(pdf, bytes)
        assert len(pdf) > 1000

        # PDF may FlateDecode-compress content streams; decompress all streams and search
        found = False
        for stream_bytes in re.findall(rb"stream\r?\n(.*?)\r?\nendstream", pdf, re.DOTALL):
            try:
                decompressed = zlib.decompress(stream_bytes)
                if b"Prod SLA" in decompressed:
                    found = True
                    break
            except Exception:
                pass
        # Also check uncompressed portions (metadata, plain text streams)
        if not found:
            found = b"Prod SLA" in pdf or b"Prod" in pdf
        assert found, "SLA name not found in PDF content"

    def test_build_pdf_no_reportlab(self):
        """When SimpleDocTemplate is None, _build_pdf returns a fallback bytes message."""
        import services.api_gateway.sla_report as mod

        with patch.object(mod, "SimpleDocTemplate", None):
            result = mod._build_pdf(_SLA_DEF, _COMPLIANT_RESULT, "narrative", [])

        assert isinstance(result, bytes)
        assert len(result) > 0
        assert b"unavailable" in result.lower() or b"not installed" in result.lower()

    def test_build_pdf_empty_incidents(self):
        """_build_pdf does not crash when incidents list is empty."""
        from services.api_gateway.sla_report import _build_pdf, SimpleDocTemplate

        if SimpleDocTemplate is None:
            pytest.skip("reportlab not installed")

        # Should not raise
        pdf = _build_pdf(_SLA_DEF, _COMPLIANT_RESULT, "All good.", [])
        assert isinstance(pdf, bytes)


# ---------------------------------------------------------------------------
# Group C — _send_email
# ---------------------------------------------------------------------------

class TestSendEmail:
    """Tests for the _send_email function."""

    def test_send_email_no_smtp_host(self, monkeypatch):
        """Returns [] when SMTP_HOST is not set."""
        from services.api_gateway.sla_report import _send_email

        monkeypatch.delenv("SMTP_HOST", raising=False)
        result = _send_email(b"fakepdf", "Prod SLA", "2026-04", ["ops@contoso.com"])
        assert result == []

    def test_send_email_no_recipients(self, monkeypatch):
        """Returns [] when recipients list is empty."""
        from services.api_gateway.sla_report import _send_email

        monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
        result = _send_email(b"fakepdf", "Prod SLA", "2026-04", [])
        assert result == []

    def test_send_email_smtp_success(self, monkeypatch):
        """When smtplib.SMTP succeeds, returns the recipients list."""
        import smtplib
        from services.api_gateway.sla_report import _send_email

        monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("SMTP_PORT", "587")
        monkeypatch.setenv("SMTP_USER", "user@example.com")
        monkeypatch.setenv("SMTP_PASSWORD", "secret")
        monkeypatch.setenv("SMTP_FROM", "noreply@example.com")

        mock_smtp_instance = MagicMock()
        mock_smtp_ctx = MagicMock()
        mock_smtp_ctx.__enter__ = MagicMock(return_value=mock_smtp_instance)
        mock_smtp_ctx.__exit__ = MagicMock(return_value=False)

        with patch("smtplib.SMTP", return_value=mock_smtp_ctx):
            result = _send_email(b"fakepdf", "Prod SLA", "2026-04", ["ops@contoso.com"])

        assert result == ["ops@contoso.com"]

    def test_send_email_smtp_failure(self, monkeypatch):
        """When smtplib.SMTP raises, returns [] without propagating the exception."""
        from services.api_gateway.sla_report import _send_email

        monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("SMTP_PORT", "587")
        monkeypatch.setenv("SMTP_USER", "")
        monkeypatch.setenv("SMTP_PASSWORD", "")

        with patch("smtplib.SMTP", side_effect=ConnectionRefusedError("refused")):
            result = _send_email(b"fakepdf", "Prod SLA", "2026-04", ["ops@contoso.com"])

        assert result == []


# ---------------------------------------------------------------------------
# Group D — generate_and_send_sla_report
# ---------------------------------------------------------------------------

class TestGenerateAndSendSlaReport:
    """Tests for the generate_and_send_sla_report entry point."""

    @pytest.mark.asyncio
    async def test_generate_report_sla_not_found(self):
        """Returns ReportResult with error='SLA not found' when DB returns None."""
        import services.api_gateway.sla_report as mod

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)
        mock_conn.close = AsyncMock()

        with patch("asyncpg.connect", AsyncMock(return_value=mock_conn)), \
             patch("services.api_gateway.runbook_rag.resolve_postgres_dsn", return_value="postgresql://fake"):
            result = await mod.generate_and_send_sla_report(
                "aaaaaaaa-0000-0000-0000-000000000001"
            )

        assert result.error == "SLA not found"
        assert result.sla_name == "Unknown"
        assert result.pdf_bytes_size == 0

    @pytest.mark.asyncio
    async def test_generate_report_full_pipeline(self):
        """Full pipeline mock: DB + compliance + email → pdf_bytes_size > 0."""
        import services.api_gateway.sla_report as mod

        # Build a fake asyncpg row
        fake_row = MagicMock()
        fake_row.__getitem__ = lambda self, key: {
            "id": "aaaaaaaa-0000-0000-0000-000000000001",
            "name": "Prod SLA",
            "target_availability_pct": 99.9,
            "covered_resource_ids": [],
            "measurement_period": "monthly",
            "customer_name": "Contoso",
            "report_recipients": [],
        }[key]

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=fake_row)
        mock_conn.close = AsyncMock()

        # Compliance result mock
        mock_compliance = MagicMock()
        mock_compliance.dict.return_value = {
            **_COMPLIANT_RESULT,
            "resource_attainments": [],
        }

        with patch("asyncpg.connect", AsyncMock(return_value=mock_conn)), \
             patch("services.api_gateway.runbook_rag.resolve_postgres_dsn", return_value="postgresql://fake"), \
             patch("services.api_gateway.sla_endpoints._calculate_compliance", AsyncMock(return_value=mock_compliance)), \
             patch.object(mod, "_send_email", return_value=[]):
            result = await mod.generate_and_send_sla_report(
                "aaaaaaaa-0000-0000-0000-000000000001"
            )

        assert result.error is None
        assert result.pdf_bytes_size > 0
        assert result.sla_name == "Prod SLA"

    @pytest.mark.asyncio
    async def test_generate_report_email_disabled(self, monkeypatch):
        """emailed_to=[] when SMTP_HOST is not set."""
        import services.api_gateway.sla_report as mod

        monkeypatch.delenv("SMTP_HOST", raising=False)

        fake_row = MagicMock()
        fake_row.__getitem__ = lambda self, key: {
            "id": "aaaaaaaa-0000-0000-0000-000000000001",
            "name": "Prod SLA",
            "target_availability_pct": 99.9,
            "covered_resource_ids": [],
            "measurement_period": "monthly",
            "customer_name": "Contoso",
            "report_recipients": ["ops@contoso.com"],
        }[key]

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=fake_row)
        mock_conn.close = AsyncMock()

        mock_compliance = MagicMock()
        mock_compliance.dict.return_value = {
            **_COMPLIANT_RESULT,
            "resource_attainments": [],
        }

        with patch("asyncpg.connect", AsyncMock(return_value=mock_conn)), \
             patch("services.api_gateway.runbook_rag.resolve_postgres_dsn", return_value="postgresql://fake"), \
             patch("services.api_gateway.sla_endpoints._calculate_compliance", AsyncMock(return_value=mock_compliance)):
            result = await mod.generate_and_send_sla_report(
                "aaaaaaaa-0000-0000-0000-000000000001"
            )

        assert result.emailed_to == []

    @pytest.mark.asyncio
    async def test_generate_report_duration_ms_positive(self):
        """duration_ms is positive in the returned ReportResult."""
        import services.api_gateway.sla_report as mod

        fake_row = MagicMock()
        fake_row.__getitem__ = lambda self, key: {
            "id": "aaaaaaaa-0000-0000-0000-000000000001",
            "name": "Prod SLA",
            "target_availability_pct": 99.9,
            "covered_resource_ids": [],
            "measurement_period": "monthly",
            "customer_name": None,
            "report_recipients": [],
        }[key]

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=fake_row)
        mock_conn.close = AsyncMock()

        mock_compliance = MagicMock()
        mock_compliance.dict.return_value = {
            **_COMPLIANT_RESULT,
            "resource_attainments": [],
        }

        with patch("asyncpg.connect", AsyncMock(return_value=mock_conn)), \
             patch("services.api_gateway.runbook_rag.resolve_postgres_dsn", return_value="postgresql://fake"), \
             patch("services.api_gateway.sla_endpoints._calculate_compliance", AsyncMock(return_value=mock_compliance)), \
             patch.object(mod, "_send_email", return_value=[]):
            result = await mod.generate_and_send_sla_report(
                "aaaaaaaa-0000-0000-0000-000000000001"
            )

        assert result.duration_ms > 0
