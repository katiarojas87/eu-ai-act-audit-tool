"""Generate a branded KRS Solutions PDF audit report."""
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, PageBreak,
)

import config

TIER_COLOR = {
    "PROHIBITED": colors.HexColor("#B00020"),
    "ANNEX_I": colors.HexColor("#C75300"),
    "ANNEX_III": colors.HexColor("#C75300"),
    "LIMITED": colors.HexColor("#1E6FB8"),
    "MINIMAL": colors.HexColor("#2E7D32"),
    "GPAI": colors.HexColor("#6A1B9A"),
}
STATUS_LABEL = {
    "likely_gap": "Likely gap",
    "likely_in_place": "Likely in place",
    "needs_confirmation": "Confirm",
}
STATUS_COLOR = {
    "likely_gap": colors.HexColor("#B00020"),
    "likely_in_place": colors.HexColor("#2E7D32"),
    "needs_confirmation": colors.HexColor("#7A7A00"),
}


def generate_report(client_name: str, systems: list[dict],
                    out_dir: Path = config.REPORTS_DIR) -> Path:
    """systems: list of completed AuditState dicts."""
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in client_name if c.isalnum() or c in " -_").strip().replace(" ", "_")
    path = out_dir / f"AI_Act_Audit_{safe}_{date.today().isoformat()}.pdf"

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=20, spaceAfter=6)
    sub = ParagraphStyle("sub", parent=styles["Normal"], fontSize=10, textColor=colors.grey)
    body = styles["Normal"]
    sys_h = ParagraphStyle("sysh", parent=styles["Heading2"], fontSize=14, spaceBefore=14)

    doc = SimpleDocTemplate(str(path), pagesize=A4,
                            topMargin=2*cm, bottomMargin=2*cm,
                            leftMargin=2*cm, rightMargin=2*cm)
    story = []

    # Cover
    story.append(Paragraph("EU AI Act — Compliance Audit", h1))
    story.append(Paragraph(f"Prepared for <b>{client_name}</b>", body))
    story.append(Paragraph(
        f"{config.COMPANY_NAME} · {config.CONSULTANT_NAME} · {date.today().strftime('%d %B %Y')}",
        sub))
    story.append(Spacer(1, 0.6*cm))
    story.append(Paragraph(
        "This report classifies each AI system against Regulation (EU) 2024/1689 "
        "and lists the obligations and key compliance gaps to address.", body))
    story.append(Spacer(1, 0.4*cm))

    # Summary table
    rows = [["AI System", "Risk Tier", "GPAI", "Confidence"]]
    for s in systems:
        rows.append([s.get("system_name", "-"), s.get("tier", "-"),
                     "Yes" if s.get("is_gpai") else "—", s.get("confidence", "-")])
    t = Table(rows, colWidths=[7*cm, 4.5*cm, 2.5*cm, 3*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E6FB8")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F6FA")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(t)

    # Per-system detail
    for s in systems:
        story.append(PageBreak())
        tier = s.get("tier", "-")
        story.append(Paragraph(s.get("system_name", "AI System"), sys_h))
        tier_style = ParagraphStyle("tier", parent=body, fontSize=12,
                                    textColor=TIER_COLOR.get(tier, colors.black))
        story.append(Paragraph(f"<b>Risk tier: {tier}</b> "
                               f"{('— ' + s['annex_category']) if s.get('annex_category') else ''}",
                               tier_style))
        if s.get("is_gpai"):
            gpai_style = ParagraphStyle("gpai", parent=body, fontSize=11,
                                        textColor=TIER_COLOR["GPAI"])
            story.append(Paragraph("<b>+ Also a GPAI provider</b> "
                                   "(general-purpose / foundation model obligations apply)",
                                   gpai_style))
        if s.get("confidence") == "low":
            story.append(Paragraph("<i>⚠ Needs legal review — classification uncertain.</i>", sub))
        story.append(Spacer(1, 0.2*cm))
        story.append(Paragraph(f"<b>Rationale.</b> {s.get('rationale', '')}", body))
        if s.get("is_gpai") and s.get("gpai_rationale"):
            story.append(Paragraph(f"<b>GPAI rationale.</b> {s['gpai_rationale']}", body))
        if s.get("triggering_articles"):
            story.append(Paragraph(
                "<b>Triggering provisions:</b> " + ", ".join(s["triggering_articles"]), body))
        story.append(Spacer(1, 0.3*cm))

        obl = s.get("obligations") or []
        if obl:
            story.append(Paragraph("<b>Obligations &amp; compliance gaps</b>", body))
            orows = [["Obligation", "Deadline", "Status", "Assessment / gap check"]]
            for o in obl:
                assessment = o.get("reasoning") or o.get("gap_question", "")
                orows.append([o.get("obligation", ""), o.get("deadline", ""),
                              STATUS_LABEL.get(o.get("status"), "Confirm"), assessment])
            ot = Table(orows, colWidths=[4.5*cm, 2.5*cm, 2.3*cm, 7.7*cm])
            style = [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#33415C")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
            # colour the Status cell by assessment
            for ri, o in enumerate(obl, start=1):
                style.append(("TEXTCOLOR", (2, ri), (2, ri),
                              STATUS_COLOR.get(o.get("status"), colors.grey)))
            ot.setStyle(TableStyle(style))
            story.append(ot)

    story.append(Spacer(1, 0.8*cm))
    story.append(Paragraph(
        "Disclaimer: this audit is a structured assessment to support compliance "
        "planning and is not legal advice. Final classification of high-risk and "
        "prohibited systems should be confirmed with qualified legal counsel.", sub))

    doc.build(story)
    return path
