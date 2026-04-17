from __future__ import annotations
"""SLA monthly report generation — PDF + GPT-4o narrative + SMTP email (Phase 55).

Entry point: generate_and_send_sla_report(sla_id) -> ReportResult
"""
import os

import io
import logging
import os
import smtplib
import time
import uuid
from datetime import datetime, timezone
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
except ImportError:
    SimpleDocTemplate = None  # type: ignore[assignment,misc]
    colors = None  # type: ignore[assignment,misc]
    getSampleStyleSheet = None  # type: ignore[assignment,misc]
    Paragraph = None  # type: ignore[assignment,misc]
    Spacer = None  # type: ignore[assignment,misc]
    Table = None  # type: ignore[assignment,misc]
    TableStyle = None  # type: ignore[assignment,misc]
    A4 = None  # type: ignore[assignment,misc]
    logger.warning("reportlab not installed — PDF generation disabled")

try:
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential as _DefaultCred
except ImportError:
    AIProjectClient = None  # type: ignore[assignment,misc]
    _DefaultCred = None  # type: ignore[assignment,misc]
    logger.warning("azure-ai-projects not installed — narrative generation disabled")

from pydantic import BaseModel


class ReportResult(BaseModel):
    sla_id: str
    sla_name: str
    report_period: str
    attained_availability_pct: Optional[float]
    is_compliant: Optional[bool]
    pdf_bytes_size: int
    emailed_to: list[str]
    narrative_generated: bool
    duration_ms: float
    error: Optional[str] = None


def _fallback_narrative(compliance_result: dict, sla_def: dict) -> str:
    attained = compliance_result.get("attained_availability_pct")
    target = sla_def.get("target_availability_pct")
    period = (compliance_result.get("period_start") or "")[:7]
    if attained is None:
        return f"Availability data was unavailable for period {period}. Manual review required."
    status = "met" if compliance_result.get("is_compliant") else "not met"
    return (
        f"For period {period}, the '{sla_def['name']}' SLA attained "
        f"{attained:.3f}% availability against a target of {target}%. "
        f"The SLA was {status}."
    )


def _build_narrative(compliance_result: dict, sla_def: dict) -> str:
    """Generate a 2-3 sentence plain-English SLA attainment summary."""
    if AIProjectClient is None or _DefaultCred is None:
        return _fallback_narrative(compliance_result, sla_def)

    endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT", "")
    if not endpoint:
        return _fallback_narrative(compliance_result, sla_def)

    try:
        client = AIProjectClient(endpoint=endpoint, credential=_DefaultCred())
        attained = compliance_result.get("attained_availability_pct")
        target = sla_def.get("target_availability_pct")
        period = (compliance_result.get("period_start") or "")[:7]
        status = "met" if compliance_result.get("is_compliant") else "NOT met"
        prompt = (
            f"Write a 2-3 sentence professional SLA compliance summary for a customer report. "
            f"SLA name: '{sla_def['name']}'. Target: {target}% availability. "
            f"Attained: {attained:.3f}% in period {period}. "
            f"SLA was {status}. "
            f"Mention any significant downtime events if attainment is below target."
        )
        response = client.inference.get_chat_completions(
            model_name=os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1"),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        logger.warning("GPT-4o narrative generation failed: %s", exc)
        return _fallback_narrative(compliance_result, sla_def)


def _build_pdf(
    sla_def: dict,
    compliance_result: dict,
    narrative: str,
    incidents: list[dict],
) -> bytes:
    """Build PDF report in memory. Returns bytes."""
    if SimpleDocTemplate is None:
        return b"PDF generation unavailable: reportlab not installed."

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    styles = getSampleStyleSheet()
    story = []

    # Cover
    title = f"SLA Compliance Report — {sla_def.get('name', 'Unknown')}"
    story.append(Paragraph(title, styles["Title"]))
    story.append(Spacer(1, 0.5 * cm))
    customer = sla_def.get("customer_name") or "N/A"
    story.append(Paragraph(f"Customer: {customer}", styles["Normal"]))
    period_start = compliance_result.get("period_start", "")
    period_end = compliance_result.get("period_end", "")
    story.append(Paragraph(f"Period: {period_start} – {period_end}", styles["Normal"]))
    story.append(Paragraph(f"Generated: {datetime.now(timezone.utc).isoformat()}", styles["Normal"]))
    story.append(Spacer(1, cm))

    # Section 1: Attainment Summary
    story.append(Paragraph("Attainment Summary", styles["Heading2"]))
    attained = compliance_result.get("attained_availability_pct")
    target = sla_def.get("target_availability_pct")
    is_compliant = compliance_result.get("is_compliant")
    status_text = "COMPLIANT ✓" if is_compliant else ("BREACH ✗" if is_compliant is False else "N/A")
    row_color = (
        colors.HexColor("#d4edda") if is_compliant
        else (colors.HexColor("#f8d7da") if is_compliant is False else colors.white)
    )
    header_color = colors.HexColor("#0078D4")
    summary_data = [
        ["Metric", "Value"],
        ["Target Availability", f"{target}%"],
        ["Attained", f"{attained:.3f}%" if attained is not None else "N/A"],
        ["Status", status_text],
        ["Period", period_start[:7] if period_start else "N/A"],
    ]
    tbl = Table(summary_data, colWidths=[8 * cm, 8 * cm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), header_color),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 3), (-1, 3), row_color),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9f9f9")]),
    ]))
    story.append(tbl)
    story.append(Spacer(1, cm))

    # Section 2: Resource Breakdown
    story.append(Paragraph("Resource Breakdown", styles["Heading2"]))
    resource_rows = [["Resource ID", "Availability %", "Downtime (min)", "Data Source"]]
    for ra in compliance_result.get("resource_attainments", []):
        resource_rows.append([
            str(ra.get("resource_id", ""))[-40:],
            f"{ra.get('availability_pct', 0):.3f}%" if ra.get("availability_pct") is not None else "N/A",
            str(ra.get("downtime_minutes", 0) or 0),
            str(ra.get("data_source", "")),
        ])
    if len(resource_rows) == 1:
        resource_rows.append(["No resources", "—", "—", "—"])
    res_tbl = Table(resource_rows, colWidths=[5 * cm, 4 * cm, 4 * cm, 4 * cm])
    res_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), header_color),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    story.append(res_tbl)
    story.append(Spacer(1, cm))

    # Section 3: Contributing Incidents
    story.append(Paragraph("Contributing Incidents", styles["Heading2"]))
    inc_rows = [["Incident ID", "Title", "Severity", "Start", "Duration"]]
    for inc in incidents:
        inc_rows.append([
            str(inc.get("incident_id", ""))[:16],
            str(inc.get("title", ""))[:40],
            str(inc.get("severity", "")),
            str(inc.get("occurred_at", ""))[:19],
            str(inc.get("duration_minutes", "")) + " min",
        ])
    if len(inc_rows) == 1:
        inc_rows.append(["No incidents", "—", "—", "—", "—"])
    inc_tbl = Table(inc_rows, colWidths=[3.5 * cm, 6 * cm, 3 * cm, 4 * cm, 3 * cm])
    inc_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), header_color),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    story.append(inc_tbl)
    story.append(Spacer(1, cm))

    # Section 4: Narrative
    story.append(Paragraph("Executive Summary", styles["Heading2"]))
    story.append(Paragraph(narrative, styles["Normal"]))

    doc.build(story)
    return buf.getvalue()


def _send_email(pdf_bytes: bytes, sla_name: str, period: str, recipients: list[str]) -> list[str]:
    """Send PDF report via SMTP. Returns list of recipients actually emailed."""
    smtp_host = os.environ.get("SMTP_HOST", "")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_password = os.environ.get("SMTP_PASSWORD", "")
    smtp_from = os.environ.get("SMTP_FROM", smtp_user)

    if not smtp_host or not recipients:
        logger.info("SMTP not configured or no recipients — skipping email delivery")
        return []

    msg = MIMEMultipart()
    msg["From"] = smtp_from
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = f"SLA Compliance Report — {sla_name} — {period}"

    body = MIMEText(
        f"Please find attached the SLA compliance report for '{sla_name}' "
        f"covering period {period}.\n\nThis report was generated automatically "
        f"by the Azure Agentic Platform.",
        "plain",
    )
    msg.attach(body)

    attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
    attachment.add_header(
        "Content-Disposition",
        "attachment",
        filename=f"sla-report-{sla_name.lower().replace(' ', '-')}-{period}.pdf",
    )
    msg.attach(attachment)

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.ehlo()
            if smtp_port != 465:
                server.starttls()
                server.ehlo()
            if smtp_user and smtp_password:
                server.login(smtp_user, smtp_password)
            server.sendmail(smtp_from, recipients, msg.as_string())
        logger.info("SLA report emailed to %s recipients", len(recipients))
        return recipients
    except Exception as exc:
        logger.error("SMTP delivery failed: %s", exc)
        return []


async def generate_and_send_sla_report(sla_id: str) -> ReportResult:
    """Main entry point: fetch SLA, compute compliance, build PDF, email it."""
    import asyncpg
    from services.api_gateway.runbook_rag import resolve_postgres_dsn
    from services.api_gateway.sla_endpoints import _calculate_compliance

    start_time = time.monotonic()

    # Load SLA definition
    try:
        dsn = resolve_postgres_dsn()
        conn = await asyncpg.connect(dsn)
        try:
            row = await conn.fetchrow(
                "SELECT * FROM sla_definitions WHERE id = $1 AND is_active = TRUE",
                uuid.UUID(sla_id),
            )
        finally:
            await conn.close()
    except Exception as exc:
        logger.error("Failed to load SLA definition %s: %s", sla_id, exc)
        return ReportResult(
            sla_id=sla_id,
            sla_name="Unknown",
            report_period="",
            attained_availability_pct=None,
            is_compliant=None,
            pdf_bytes_size=0,
            emailed_to=[],
            narrative_generated=False,
            duration_ms=(time.monotonic() - start_time) * 1000,
            error="SLA not found",
        )

    if row is None:
        return ReportResult(
            sla_id=sla_id,
            sla_name="Unknown",
            report_period="",
            attained_availability_pct=None,
            is_compliant=None,
            pdf_bytes_size=0,
            emailed_to=[],
            narrative_generated=False,
            duration_ms=(time.monotonic() - start_time) * 1000,
            error="SLA not found",
        )

    sla_def = {
        "id": str(row["id"]),
        "name": row["name"],
        "target_availability_pct": float(row["target_availability_pct"]),
        "covered_resource_ids": list(row["covered_resource_ids"] or []),
        "measurement_period": row["measurement_period"],
        "customer_name": row["customer_name"],
        "report_recipients": list(row["report_recipients"] or []),
    }

    # Compute compliance
    compliance_result = await _calculate_compliance(row)
    compliance_dict = compliance_result.dict() if hasattr(compliance_result, "dict") else compliance_result

    # Fetch contributing incidents from Cosmos (graceful fallback)
    incidents: list[dict] = []
    try:
        cosmos_url = os.environ.get("COSMOS_URL", "")
        cosmos_key = os.environ.get("COSMOS_KEY", "")
        cosmos_db = os.environ.get("COSMOS_DATABASE_NAME", "aap")
        if cosmos_url and cosmos_key:
            from azure.cosmos import CosmosClient
            cosmos_client = CosmosClient(cosmos_url, cosmos_key)
            db = cosmos_client.get_database_client(cosmos_db)
            container = db.get_container_client("incidents")
            period_start = compliance_dict.get("period_start", "")
            query = (
                "SELECT c.id, c.title, c.severity, c.occurred_at, c.duration_minutes "
                "FROM c WHERE c.occurred_at >= @period_start"
            )
            items = list(container.query_items(
                query=query,
                parameters=[{"name": "@period_start", "value": period_start}],
                enable_cross_partition_query=True,
            ))
            covered = set(sla_def["covered_resource_ids"])
            incidents = [
                i for i in items
                if any(rid in str(i) for rid in covered)
            ][:20]
    except Exception as exc:
        logger.warning("Could not fetch incidents from Cosmos: %s", exc)
        incidents = []

    # Generate narrative
    narrative_generated = False
    try:
        narrative = _build_narrative(compliance_dict, sla_def)
        narrative_generated = AIProjectClient is not None and bool(os.environ.get("AZURE_AI_PROJECT_ENDPOINT"))
    except Exception as exc:
        logger.warning("Narrative generation failed: %s", exc)
        narrative = _fallback_narrative(compliance_dict, sla_def)

    # Build PDF
    pdf_bytes = _build_pdf(sla_def, compliance_dict, narrative, incidents)

    # Send email
    period = (compliance_dict.get("period_start") or "")[:7]
    emailed_to = _send_email(pdf_bytes, sla_def["name"], period, sla_def["report_recipients"])

    duration_ms = (time.monotonic() - start_time) * 1000

    return ReportResult(
        sla_id=sla_id,
        sla_name=sla_def["name"],
        report_period=period,
        attained_availability_pct=compliance_dict.get("attained_availability_pct"),
        is_compliant=compliance_dict.get("is_compliant"),
        pdf_bytes_size=len(pdf_bytes),
        emailed_to=emailed_to,
        narrative_generated=narrative_generated,
        duration_ms=duration_ms,
    )
