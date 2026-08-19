"""FastAPI backend for the EU AI Act audit tool (v2).

Exposes the deterministic classification (facts extraction → rule engine) as an
API for the Next.js frontend. Keeps the RAG (used to ground fact extraction),
multilingual support, and a shared-password gate.
"""
from __future__ import annotations

import logging
import os
import secrets
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

import config
from chat import answer as answer_chat
from facts import extract_facts
from gaps import assess_gaps
from report_v2 import generate_report
from rules import classify
import limits
from schema import Assessment
from scope_input import ScopeOverride, to_fact_overrides

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


# Length caps: the description is billed to the LLM, so an unbounded field is an
# unbounded invoice. These are generous for real intake and useless for abuse.
class ClassifyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=8000)
    components: str = Field(default="", max_length=8000)
    # Consultant overrides — beat anything inferred from the description.
    organisation_role: str = "unknown"          # provider / deployer / importer / …
    scope: ScopeOverride | None = None          # Article 2 facts (see scope_input.py)


class ReportRequest(BaseModel):
    client_name: str = Field(default="Client", max_length=200)
    systems: list[Assessment] = Field(max_length=50)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    assessment: Assessment
    # The full conversation so far, ending in the new user question. Capped so
    # a long-running chat cannot turn into an unbounded per-turn token bill —
    # the frontend never needs more than this to render a useful thread.
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)


def _check_password(x_app_password: str | None, client: str = "-") -> None:
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
    limits.check_not_locked_out(client)
    if not secrets.compare_digest(x_app_password or "", configured):
        # A single shared secret must not be brute-forceable.
        limits.record_auth_failure(client)
        raise HTTPException(status_code=401, detail="Incorrect password.")
    limits.clear_auth_failures(client)


@app.exception_handler(limits.LimitExceeded)
def _limit_handler(request: Request, exc: limits.LimitExceeded) -> Response:
    headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else {}
    return JSONResponse(status_code=exc.status, content={"detail": exc.message},
                        headers=headers)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": config.LLM_MODEL, **limits.usage()}


@app.post("/classify", response_model=Assessment)
def classify_endpoint(
    request: Request,
    body: ClassifyRequest,
    x_app_password: str | None = Header(default=None),
    x_forwarded_for: str | None = Header(default=None),
) -> Assessment:
    client = limits.client_id(x_forwarded_for,
                              request.client.host if request.client else "-")
    _check_password(x_app_password, client)
    limits.check_rate(client)
    if not body.name.strip() or not body.description.strip():
        raise HTTPException(status_code=400,
                            detail="System name and description are required.")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=500, detail="Server missing ANTHROPIC_API_KEY.")
    limits.check_daily_cap()
    try:
        facts = extract_facts(body.name, body.description, body.components,
                              organisation_role=body.organisation_role,
                              overrides=to_fact_overrides(body.scope))
        assessment = classify(facts, system_name=body.name)
        assessment.obligations = assess_gaps(
            assessment.obligations, body.description, body.components)
        return assessment
    except Exception as e:  # noqa: BLE001
        # Log the detail server-side; return a generic message so backend
        # internals and provider errors are not echoed to the browser.
        limits.refund_daily()   # the spend did not happen
        log.exception("classification failed for system %r", body.name)
        if "credit balance" in str(e).lower():
            raise HTTPException(
                status_code=402,
                detail="The AI provider account is out of credit. Top up to continue.")
        raise HTTPException(status_code=500, detail="Classification failed.")


@app.post("/chat")
def chat_endpoint(
    request: Request,
    body: ChatRequest,
    x_app_password: str | None = Header(default=None),
    x_forwarded_for: str | None = Header(default=None),
) -> dict:
    client = limits.client_id(x_forwarded_for,
                              request.client.host if request.client else "-")
    _check_password(x_app_password, client)
    limits.check_rate(client)
    if body.messages[-1].role != "user":
        raise HTTPException(status_code=400,
                            detail="The last message must be from the user.")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=500, detail="Server missing ANTHROPIC_API_KEY.")
    limits.check_daily_chat_cap()
    try:
        reply = answer_chat(body.assessment,
                            [m.model_dump() for m in body.messages])
        return {"reply": reply}
    except Exception as e:  # noqa: BLE001
        limits.refund_daily_chat()   # the spend did not happen
        log.exception("chat failed for system %r", body.assessment.system_name)
        if "credit balance" in str(e).lower():
            raise HTTPException(
                status_code=402,
                detail="The AI provider account is out of credit. Top up to continue.")
        raise HTTPException(status_code=500, detail="Chat failed.")


@app.post("/report")
def report_endpoint(
    request: Request,
    body: ReportRequest,
    x_app_password: str | None = Header(default=None),
    x_forwarded_for: str | None = Header(default=None),
) -> Response:
    client = limits.client_id(x_forwarded_for,
                              request.client.host if request.client else "-")
    _check_password(x_app_password, client)
    limits.check_rate(client)
    if not body.systems:
        raise HTTPException(status_code=400, detail="No systems to report.")
    # Build into a temporary directory that is removed straight away. Client
    # names must not accumulate on the server's filesystem: the report is the
    # client's document, and the server has no reason to keep a copy.
    with tempfile.TemporaryDirectory() as tmp:
        path = generate_report(body.client_name or "Client", body.systems,
                               out_dir=Path(tmp))
        pdf = path.read_bytes()
        filename = path.name
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
