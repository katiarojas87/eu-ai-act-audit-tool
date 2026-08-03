"""FastAPI backend for the EU AI Act audit tool (v2).

Exposes the deterministic classification (facts extraction → rule engine) as an
API for the Next.js frontend. Keeps the RAG (used to ground fact extraction),
multilingual support, and a shared-password gate.
"""
from __future__ import annotations

import os

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

import config
from facts import extract_facts
from report_v2 import generate_report
from rules import classify
from schema import Assessment

app = FastAPI(title="EU AI Act Audit API", version="2.0")

# The frontend runs on a different origin; allow it (tighten via FRONTEND_ORIGIN).
_origin = os.environ.get("FRONTEND_ORIGIN", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[_origin] if _origin != "*" else ["*"],
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)


class ClassifyRequest(BaseModel):
    name: str
    description: str
    components: str = ""


class ReportRequest(BaseModel):
    client_name: str
    systems: list[Assessment]


def _check_password(x_app_password: str | None) -> None:
    configured = os.environ.get("APP_PASSWORD")
    if configured and x_app_password != configured:
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
        facts = extract_facts(body.name, body.description, body.components)
        return classify(facts, system_name=body.name)
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        status = 402 if "credit balance" in msg.lower() else 500
        raise HTTPException(status_code=status, detail=msg)


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
