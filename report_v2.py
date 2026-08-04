"""Branded PDF for the multi-dimensional (v2) assessment.

Sections: executive summary · system & organisation profile · classification
matrix · triggered rules · potential obligations · missing evidence ·
recommended actions · sources & limitations · preliminary-not-legal-advice notice.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

import config
from schema import Assessment

NAVY = colors.HexColor("#1B2A4A")
BLUE = colors.HexColor("#2F6DB5")
AMBER = colors.HexColor("#B8873A")
INK = colors.HexColor("#22252B")
MUTE = colors.HexColor("#6A6D73")
LINE = colors.HexColor("#D8D5CC")

TIER_COLOR = {
    "PROHIBITED": colors.HexColor("#B0203C"), "ANNEX_I": AMBER, "ANNEX_III": AMBER,
    "LIMITED": BLUE, "MINIMAL": colors.HexColor("#2E7D46"), "NOT_AI": MUTE,
    "UNDETERMINED": MUTE,
}
STATUS_COLOR = {"definitive": NAVY, "conditional": AMBER, "unresolved": colors.HexColor("#B0203C")}
OBL_STATUS_LABEL = {"likely_gap": "Likely gap", "likely_in_place": "Likely in place",
                    "needs_confirmation": "Confirm"}
OBL_STATUS_COLOR = {"likely_gap": colors.HexColor("#B0203C"),
                    "likely_in_place": colors.HexColor("#2E7D46"), "needs_confirmation": AMBER}

_ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=_ss["Heading1"], fontName="Helvetica-Bold",
                    fontSize=20, textColor=NAVY, spaceAfter=6)
H2 = ParagraphStyle("H2", parent=_ss["Heading2"], fontName="Helvetica-Bold",
                    fontSize=12.5, textColor=NAVY, spaceBefore=14, spaceAfter=5)
BODY = ParagraphStyle("BODY", parent=_ss["Normal"], fontName="Helvetica",
                      fontSize=9.5, textColor=INK, leading=13)
SMALL = ParagraphStyle("SMALL", parent=BODY, fontSize=8, textColor=MUTE)
EYEBROW = ParagraphStyle("EY", parent=BODY, fontSize=8.5, textColor=AMBER)
CELL = ParagraphStyle("CELL", parent=BODY, fontSize=8, leading=10)


def _matrix_row(label, c):
    # Provisions can be long → wrap in a Paragraph so it stays inside the cell.
    return [label, c.result, Paragraph("  ".join(c.articles), CELL), c.status]


def _table(rows, widths, header_bg=NAVY, status_col=None):
    t = Table(rows, colWidths=widths)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), header_bg),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F3EE")]),
    ]
    if status_col is not None:
        for ri in range(1, len(rows)):
            st = rows[ri][status_col]
            style.append(("TEXTCOLOR", (status_col, ri), (status_col, ri),
                          STATUS_COLOR.get(st, MUTE)))
    t.setStyle(TableStyle(style))
    return t


def _recommended_actions(a: Assessment) -> list[str]:
    acts = []
    if a.tier == "PROHIBITED":
        if a.prohibited_practice.status == "conditional":
            acts.append("Suspend use pending legal review — the system matches an "
                        "Article 5 prohibition, but a statutory exception may apply: "
                        f"{a.prohibited_practice.detail} Confirm with counsel before "
                        "either continuing or shutting down.")
        else:
            acts.append("Cease use of this system immediately and seek legal counsel — "
                        "it matches an Article 5 prohibition.")
    if a.tier == "UNDETERMINED":
        acts.append("Establish first whether this is an AI system within Art. 3(1); "
                    "no reliable classification is possible until that is settled.")
    if a.high_risk.result == "ANNEX_III_EXEMPT":
        acts.append("Document the Art. 6(3) assessment before placing the system on the "
                    "market (Art. 6(4)) and register it under Art. 49(2). The derogation "
                    "fails if the system profiles natural persons — verify this.")
    if a.tier in ("ANNEX_I", "ANNEX_III"):
        if "provider" in a.roles or a.roles == ["unknown"]:
            acts += [
                f"Begin Annex IV technical documentation and data-governance / bias "
                f"review now (deadline {a.application_date}).",
                "Design effective human oversight and a post-market monitoring plan.",
                "Plan the conformity assessment, CE marking and EU-database registration.",
            ]
        if "deployer" in a.roles or a.roles == ["unknown"]:
            acts += [
                "Assign human oversight to named, trained staff and confirm you can "
                "retain the system's logs for at least six months (Art. 26).",
                "If the system is used at the workplace, inform workers' representatives "
                "before it goes live (Art. 26(7)).",
            ]
    if a.transparency.result == "Yes":
        acts.append("Add AI disclosure / synthetic-content labelling before 2 August 2026.")
    if a.is_gpai:
        acts.append("Prepare GPAI model documentation, a copyright-compliance policy and a "
                    "public training-data summary.")
    if a.missing_information:
        acts.append("Confirm the missing facts listed above before finalising the classification.")
    if not acts:
        acts.append("No mandatory obligations identified; keep records and re-assess if the "
                    "system's purpose changes.")
    return acts


def _sources(a: Assessment) -> list[str]:
    arts = set()
    for c in (a.is_ai_system, a.prohibited_practice, a.high_risk, a.transparency, a.gpai):
        arts.update(c.articles)
    return sorted(arts)


def generate_report(client_name: str, assessments: list[Assessment],
                    out_dir: Path = config.REPORTS_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch for ch in client_name if ch.isalnum() or ch in " -_").strip().replace(" ", "_")
    path = out_dir / f"AI_Act_Assessment_{safe}_{date.today().isoformat()}.pdf"

    doc = SimpleDocTemplate(str(path), pagesize=A4, topMargin=1.8 * cm,
                            bottomMargin=1.8 * cm, leftMargin=2 * cm, rightMargin=2 * cm)
    S = []

    # cover / executive summary
    S.append(Paragraph("EU AI ACT — PRELIMINARY ASSESSMENT", EYEBROW))
    S.append(Paragraph(f"Compliance assessment for {client_name}", H1))
    S.append(Paragraph(f"{config.COMPANY_NAME} · {config.CONSULTANT_NAME} · "
                       f"{date.today().strftime('%d %B %Y')}", SMALL))
    S.append(HRFlowable(width="100%", thickness=1, color=AMBER, spaceBefore=8, spaceAfter=10))
    S.append(Paragraph("<b>Executive summary.</b> This report classifies each AI system "
                       "against Regulation (EU) 2024/1689 across independent dimensions "
                       "(prohibited practice, high-risk, transparency, GPAI), using a "
                       "deterministic rule engine. Each conclusion cites the provision that "
                       "triggered it and its certainty. This is a decision-support tool, not "
                       "legal advice or certification.", BODY))

    sumrows = [["System", "Tier", "GPAI", "Confidence", "Human review"]]
    for a in assessments:
        sumrows.append([a.system_name, a.tier, "Yes" if a.is_gpai else "—",
                        a.confidence, "Yes" if a.human_review_required else "No"])
    S.append(Spacer(1, 8))
    S.append(_table(sumrows, [6.2 * cm, 3 * cm, 1.6 * cm, 2.4 * cm, 2.8 * cm]))

    for a in assessments:
        S.append(PageBreak())
        tc = TIER_COLOR.get(a.tier, MUTE)
        S.append(Paragraph(a.system_name or "AI system", H1))
        S.append(Paragraph(f"<b><font color='{tc.hexval()}'>Headline tier: {a.tier}</font></b>"
                           f"{'  ·  + GPAI provider' if a.is_gpai else ''}", BODY))

        S.append(Paragraph("System &amp; organisation profile", H2))
        prof = [["Role(s) in the value chain", " + ".join(a.roles) or a.organisation_role],
                ["Role derived from",
                 Paragraph((a.role_basis.detail if a.role_basis else "—"), CELL)],
                ["Application date", a.application_date],
                ["Confidence", a.confidence],
                ["Human review required", "Yes" if a.human_review_required else "No"]]
        S.append(_table([["Field", "Value"]] + prof, [5 * cm, 12 * cm]))

        S.append(Paragraph("Classification matrix", H2))
        matrix = [["Dimension", "Result", "Provision(s)", "Status"],
                  _matrix_row("Is it an AI system?", a.is_ai_system),
                  _matrix_row("Prohibited practice", a.prohibited_practice),
                  _matrix_row("High-risk system", a.high_risk),
                  _matrix_row("Transparency obligations", a.transparency),
                  _matrix_row("GPAI relationship", a.gpai)]
        S.append(_table(matrix, [4.6 * cm, 3.2 * cm, 5.7 * cm, 3.5 * cm], status_col=3))

        S.append(Paragraph("Triggered rules", H2))
        for c, lbl in [(a.prohibited_practice, "Prohibited"), (a.high_risk, "High-risk"),
                       (a.transparency, "Transparency"), (a.gpai, "GPAI")]:
            if c.result not in ("No", "Unclear"):
                S.append(Paragraph(f"• <b>{lbl}:</b> {c.detail} "
                                   f"<font color='{MUTE.hexval()}'>({', '.join(c.articles)})</font> "
                                   f"— triggered by: {c.trigger}", BODY))

        if a.obligations:
            S.append(Paragraph("Potential obligations &amp; gaps", H2))
            if a.roles == ["unknown"]:
                S.append(Paragraph(
                    "<b>Role not established.</b> Both the provider and the deployer "
                    "list are shown below. They are not cumulative — confirm the "
                    "client's role and drop the list that does not apply. A deployer "
                    "does not owe conformity assessment or CE marking.", SMALL))
                S.append(Spacer(1, 4))

            # One table per role, so nobody reads the manufacturer's duties as
            # their own.
            for r in sorted({o.role for o in a.obligations},
                            key=lambda x: (x == "all", x)):
                rows = [o for o in a.obligations if o.role == r]
                heading = ("Applies to everyone in scope" if r == "all"
                           else f"As {r}")
                S.append(Spacer(1, 6))
                S.append(Paragraph(f"<b>{heading}</b>", BODY))
                S.append(Spacer(1, 3))
                orows = [["Obligation", "Article", "Deadline", "Assessment", "Status"]]
                for o in rows:
                    orows.append([Paragraph(o.obligation, CELL),
                                  Paragraph(o.article, CELL),
                                  Paragraph(o.deadline, CELL),
                                  Paragraph(o.reasoning or o.gap_question, CELL),
                                  OBL_STATUS_LABEL.get(o.status, "Confirm")])
                ot = Table(orows, colWidths=[4.4 * cm, 1.9 * cm, 2.6 * cm,
                                             5.4 * cm, 2.7 * cm])
                style = [
                    ("BACKGROUND", (0, 0), (-1, 0), BLUE),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("GRID", (0, 0), (-1, -1), 0.4, LINE),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                     [colors.white, colors.HexColor("#F5F3EE")]),
                ]
                for ri, o in enumerate(rows, start=1):
                    style.append(("TEXTCOLOR", (4, ri), (4, ri),
                                  OBL_STATUS_COLOR.get(o.status, MUTE)))
                ot.setStyle(TableStyle(style))
                S.append(ot)

        S.append(Paragraph("Missing evidence", H2))
        if a.missing_information:
            S.append(Paragraph("The description did not establish the facts below. They were "
                               "left unresolved rather than assumed — confirm them before "
                               "relying on this assessment.", SMALL))
            S.append(Spacer(1, 3))
            for m in a.missing_information:
                S.append(Paragraph(f"• {m}", BODY))
        else:
            S.append(Paragraph("None — all decisive facts were established.", BODY))

        S.append(Paragraph("Recommended actions", H2))
        for act in _recommended_actions(a):
            S.append(Paragraph(f"• {act}", BODY))

        S.append(Paragraph("Sources &amp; limitations", H2))
        seen = set()
        for c in (a.is_ai_system, a.prohibited_practice, a.high_risk, a.transparency, a.gpai):
            for s in c.sources:
                if s.ref in seen:
                    continue
                seen.add(s.ref)
                # A recital is an interpretive aid, not the rule — say so, in red,
                # rather than presenting it as the binding provision.
                if s.kind == "recital":
                    tag = (f" <font color='{colors.HexColor('#B0203C').hexval()}'>"
                           "[recital — non-binding, interpretive only]</font>")
                else:
                    tag = ""
                S.append(Paragraph(f"<b>{s.ref}</b>{tag} — <i>“{s.quote}”</i>", CELL))
                S.append(Paragraph(f"{s.location} · {s.url}", SMALL))
                S.append(Spacer(1, 4))
        if not seen:
            S.append(Paragraph("Provisions cited: " + " · ".join(_sources(a)), SMALL))

        unsourced = sorted({r for c in (a.is_ai_system, a.prohibited_practice,
                                        a.high_risk, a.transparency, a.gpai)
                            for r in c.unsourced})
        if unsourced:
            S.append(Spacer(1, 4))
            S.append(Paragraph(
                "<b>Confirmation needed —</b> the wording of the following provisions "
                "could not be located verbatim in the source text and was not "
                "interpreted: " + " · ".join(unsourced) +
                ". Verify these directly against the official text before relying on them.",
                ParagraphStyle("warn", parent=SMALL, textColor=colors.HexColor("#B0203C"))))
        S.append(Paragraph("Based on Regulation (EU) 2024/1689 (Annexes I &amp; III, "
                           "Article 5, GPAI rules) and the curated knowledge base. "
                           "Classification is deterministic; fact extraction from the "
                           "description may be incomplete — see missing evidence.", SMALL))

    S.append(Spacer(1, 14))
    S.append(HRFlowable(width="100%", thickness=1, color=AMBER, spaceBefore=4, spaceAfter=6))
    S.append(Paragraph("<b>PRELIMINARY ASSESSMENT — NOT LEGAL ADVICE.</b> This document "
                       "supports compliance planning. It does not constitute legal advice, "
                       "EU approval, certification, or a guarantee of compliance. High-risk "
                       "and prohibited determinations must be confirmed with qualified counsel.",
                       SMALL))

    doc.build(S)
    return path
