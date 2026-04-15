"""Compliance posture and export API endpoints (Phase 54).

Provides:
  GET /api/v1/compliance/posture  — per-framework compliance scores
  GET /api/v1/compliance/export   — PDF or CSV audit report
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse

from services.api_gateway.dependencies import get_credential
from services.api_gateway.compliance_posture import (
    compute_posture,
    fetch_defender_assessments,
    fetch_policy_compliance,
    get_compliance_mappings,
    get_cached_posture,
    set_cached_posture,
)

# reportlab for PDF generation — optional; falls back gracefully if not installed
try:
    from reportlab.lib.pagesizes import A4  # type: ignore[import]
    from reportlab.platypus import (  # type: ignore[import]
        SimpleDocTemplate,
        Table,
        TableStyle,
        Paragraph,
        Spacer,
    )
    from reportlab.lib.styles import getSampleStyleSheet  # type: ignore[import]
    from reportlab.lib import colors  # type: ignore[import]
    _REPORTLAB_AVAILABLE = True
except ImportError:
    _REPORTLAB_AVAILABLE = False

router = APIRouter(prefix="/api/v1/compliance", tags=["compliance"])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _build_posture(
    subscription_id: str,
    credential: Any,
) -> dict[str, Any]:
    """Fetch live data and compute posture. Returns the posture dict."""
    # Load mapping rows from PostgreSQL (cached 24h)
    try:
        mappings = await get_compliance_mappings()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load compliance mappings: %s", exc)
        mappings = []

    if not mappings:
        return {}

    # Fetch live assessment + policy data in parallel
    assessments, policy_states = await asyncio.gather(
        fetch_defender_assessments(credential, subscription_id),
        fetch_policy_compliance(credential, subscription_id),
    )

    posture = compute_posture(
        mappings=mappings,
        assessments=assessments,
        policy_states=policy_states,
        subscription_id=subscription_id,
    )
    return posture


def _generate_csv(posture: dict[str, Any], framework_filter: Optional[str]) -> io.StringIO:
    """Generate CSV report from posture data."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["framework", "control_id", "control_title", "status",
                     "finding_display_name", "severity"])

    controls = posture.get("controls", [])
    for ctrl in controls:
        if framework_filter and ctrl.get("framework") != framework_filter:
            continue
        for finding in ctrl.get("findings", []):
            writer.writerow([
                ctrl.get("framework", ""),
                ctrl.get("control_id", ""),
                ctrl.get("control_title", ""),
                ctrl.get("status", ""),
                finding.get("display_name", ""),
                finding.get("severity", ""),
            ])
        # If no findings, still emit one row for the control
        if not ctrl.get("findings"):
            writer.writerow([
                ctrl.get("framework", ""),
                ctrl.get("control_id", ""),
                ctrl.get("control_title", ""),
                ctrl.get("status", ""),
                "",
                "",
            ])

    buf.seek(0)
    return buf


def _generate_pdf(posture: dict[str, Any], framework_filter: Optional[str]) -> io.BytesIO:
    """Generate PDF compliance report using reportlab."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=30, leftMargin=30,
                            topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    story = []

    subscription_id = posture.get("subscription_id", "unknown")
    generated_at = posture.get("generated_at", "")
    date_str = generated_at[:10] if generated_at else datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    # Title
    story.append(Paragraph(f"Compliance Posture Report", styles["Title"]))
    story.append(Paragraph(f"Subscription: {subscription_id}", styles["Normal"]))
    story.append(Paragraph(f"Generated: {generated_at}", styles["Normal"]))
    story.append(Spacer(1, 20))

    # Framework scores summary table
    frameworks = posture.get("frameworks", {})
    fw_data = [["Framework", "Score", "Passing", "Failing", "Not Assessed"]]
    for fw_name, fw_stats in frameworks.items():
        if framework_filter and fw_name != framework_filter:
            continue
        fw_data.append([
            fw_name.upper(),
            f"{fw_stats.get('score', 0):.1f}%",
            str(fw_stats.get("passing", 0)),
            str(fw_stats.get("failing", 0)),
            str(fw_stats.get("not_assessed", 0)),
        ])

    if len(fw_data) > 1:
        story.append(Paragraph("Framework Summary", styles["Heading2"]))
        fw_table = Table(fw_data, colWidths=[80, 80, 80, 80, 100])
        fw_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0078D4")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F9FE")]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(fw_table)
        story.append(Spacer(1, 16))

    # Controls detail
    controls = posture.get("controls", [])
    for fw_name in (["asb", "cis", "nist"] if not framework_filter else [framework_filter]):
        fw_controls = [c for c in controls if c.get("framework") == fw_name]
        if not fw_controls:
            continue

        story.append(Paragraph(f"{fw_name.upper()} Controls", styles["Heading2"]))

        ctrl_data = [["Control ID", "Title", "Status", "Findings"]]
        for ctrl in fw_controls:
            status = ctrl.get("status", "not_assessed")
            findings_count = len(ctrl.get("findings", []))
            ctrl_data.append([
                ctrl.get("control_id", ""),
                ctrl.get("control_title", "")[:50],  # truncate long titles
                status,
                str(findings_count),
            ])

        if len(ctrl_data) > 1:
            ctrl_table = Table(ctrl_data, colWidths=[70, 250, 90, 60])
            ctrl_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0078D4")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F9FE")]),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            story.append(ctrl_table)
            story.append(Spacer(1, 12))

    doc.build(story)
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/posture")
async def get_compliance_posture(
    subscription_id: str = Query(..., description="Azure subscription ID"),
    framework: Optional[str] = Query(
        None, description="Filter by framework: asb | cis | nist"
    ),
    credential: Any = Depends(get_credential),
) -> Dict[str, Any]:
    """Return compliance posture scores per framework for a subscription.

    Scores are cached for 1 hour per subscription. The response includes:
    - Per-framework scores (ASB, CIS v8, NIST 800-53 Rev 5)
    - Control-level status (passing / failing / not_assessed)
    - Individual findings driving each control status
    """
    cache_hit = False

    # Check posture cache first
    cached = get_cached_posture(subscription_id)
    if cached is not None:
        posture = cached
        cache_hit = True
    else:
        posture = await _build_posture(subscription_id, credential)

        if not posture:
            return JSONResponse(
                status_code=404,
                content={"error": "No compliance mappings configured. Run the seed script."},
            )

        set_cached_posture(subscription_id, posture)

    # Apply framework filter to controls list if requested
    valid_frameworks = {"asb", "cis", "nist"}
    if framework:
        framework = framework.lower()
        if framework not in valid_frameworks:
            return JSONResponse(
                status_code=422,
                content={"error": f"framework must be one of: {sorted(valid_frameworks)}"},
            )
        filtered_posture = dict(posture)
        filtered_posture["controls"] = [
            c for c in posture.get("controls", [])
            if c.get("framework") == framework
        ]
        filtered_posture["frameworks"] = {
            fw: stats
            for fw, stats in posture.get("frameworks", {}).items()
            if fw == framework
        }
        posture = filtered_posture

    return {**posture, "cache_hit": cache_hit}


@router.get("/export")
async def export_compliance(
    subscription_id: str = Query(..., description="Azure subscription ID"),
    format: str = Query(..., description="Export format: csv or pdf"),
    framework: Optional[str] = Query(None, description="Filter by framework: asb | cis | nist"),
    credential: Any = Depends(get_credential),
) -> StreamingResponse:
    """Export compliance report as CSV or PDF.

    - CSV: One row per control×finding with columns:
      framework, control_id, control_title, status, finding_display_name, severity
    - PDF: Formatted report with framework summary and per-framework control tables
    """
    fmt = format.lower()
    if fmt not in ("csv", "pdf"):
        return JSONResponse(
            status_code=422,
            content={"error": "format must be 'csv' or 'pdf'"},
        )

    # Get posture data (use cache if available)
    cached = get_cached_posture(subscription_id)
    if cached is not None:
        posture = cached
    else:
        posture = await _build_posture(subscription_id, credential)
        if posture:
            set_cached_posture(subscription_id, posture)

    if not posture:
        return JSONResponse(
            status_code=404,
            content={"error": "No compliance mappings configured."},
        )

    date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    fw_suffix = f"-{framework}" if framework else ""

    if fmt == "csv":
        csv_buf = _generate_csv(posture, framework_filter=framework)
        filename = f"compliance-report{fw_suffix}-{date_str}.csv"
        return StreamingResponse(
            iter([csv_buf.read()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    # PDF
    if not _REPORTLAB_AVAILABLE:
        return JSONResponse(
            status_code=501,
            content={"error": "PDF export unavailable — reportlab not installed."},
        )

    pdf_buf = _generate_pdf(posture, framework_filter=framework)
    filename = f"compliance-report{fw_suffix}-{date_str}.pdf"
    return StreamingResponse(
        iter([pdf_buf.read()]),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
