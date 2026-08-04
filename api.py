"""FastAPI backend for the EU AI Act audit tool (v2).

Exposes the deterministic classification (facts extraction → rule engine) as an
API for the Next.js frontend. Keeps the RAG (used to ground fact extraction),
multilingual support, and a shared-password gate.
"""
from __future__ import annotations

import logging
import os
import secrets

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

import config
from facts import extract_facts
from gaps import assess_gaps
from report_v2 import generate_report
from rules import classify
from schema import Assessment

log = logging.getLogger("eu_ai_act.api")

app = FastAPI(title="EU AI Act Audit API", version="2.0")

# The frontend runs on a different origin. Default to localhost dev rather than
# "*": this endpoint carries client descriptions, so a wildcard has to be an
# explicit choice (set FRONTEND_ORIGIN, comma-separated for several).
_origins = [o.strip() for o in os.environ.get(
    "FRONTEND_ORIGIN", "http://localhost:3000").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["content-type", "x-app-password"],
)


class ClassifyRequest(BaseModel):
    name: str
    description: str
    components: str = ""
    # Consultant override — "provider" / "deployer" / "importer" / "distributor".
    # Beats anything inferred from the description.
    organisation_role: str = "unknown"


class ReportRequest(BaseModel):
    client_name: str
    systems: list[Assessment]


def _check_password(x_app_password: str | None) -> None:
    """Shared-password gate.

    Fails closed: if APP_PASSWORD is not configured the endpoints refuse rather
    than serving an open, LLM-billing, client-data endpoint to the internet. Set
    ALLOW_NO_PASSWORD=1 for local development.
    """
    configured = os.environ.get("APP_PASSWORD")
    if not configured:
        if os.environ.get("ALLOW_NO_PASSWORD") == "1":
            return
        raise HTTPException(
            status_code=503,
            detail="Server not configured: set APP_PASSWORD (or ALLOW_NO_PASSWORD=1 "
                   "for local development).")
    if not secrets.compare_digest(x_app_password or "", configured):
        raise HTTPException(status_code=401, detail="Incorrect password.")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": config.LLM_MODEL}


@app.post("/classify", response_model=Assessment)
def classify_endpoint(
    body: ClassifyRequest,
    x_app_password: str | None = Header(default=None),
) -> Assessment:
    _check_password(x_app_password)
    if not body.name.strip() or not body.description.strip():
        raise HTTPException(status_code=400,
                            detail="System name and description are required.")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=500, detail="Server missing ANTHROPIC_API_KEY.")
    try:
        facts = extract_facts(body.name, body.description, body.components,
                              organisation_role=body.organisation_role)
        assessment = classify(facts, system_name=body.name)
        assessment.obligations = assess_gaps(
            assessment.obligations, body.description, body.components)
        return assessment
    except Exception as e:  # noqa: BLE001
        # Log the detail server-side; return a generic message so backend
        # internals and provider errors are not echoed to the browser.
        log.exception("classification failed for system %r", body.name)
        if "credit balance" in str(e).lower():
            raise HTTPException(
                status_code=402,
                detail="The AI provider account is out of credit. Top up to continue.")
        raise HTTPException(status_code=500, detail="Classification failed.")


@app.post("/report")
def report_endpoint(
    body: ReportRequest,
    x_app_password: str | None = Header(default=None),
) -> Response:
    _check_password(x_app_password)
    if not body.systems:
        raise HTTPException(status_code=400, detail="No systems to report.")
    path = generate_report(body.client_name or "Client", body.systems)
    pdf = path.read_bytes()
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
    )
