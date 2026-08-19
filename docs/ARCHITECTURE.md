# Architecture

```
             Next.js UI (web/) → FastAPI (api.py)
                             │
                             ▼
             facts.py  — LLM extracts structured Facts only
                             │        ▲
                             │   retriever.py → ChromaDB (local)
                             │        ▲   multilingual-e5 (local, free)
                             │   ingest.py ← knowledge/*.md + data/*.txt
                             ▼
             rules.py  — deterministic rule engine → Assessment
                             │
             citations.py — verbatim operative text per provision
                             │
             gaps.py   — LLM judges gaps against the architecture
                             ▼
             report_v2.py — branded PDF with sources
```

All backend source lives flat in `src/` (no sub-packages — `from rules import
classify` works everywhere, including inside `eval/`, because the entrypoints
put `src/` on `PYTHONPATH` rather than nesting a package).

## Modules

| File | Purpose |
|---|---|
| `src/config.py` | Models, paths, chunking, branding — tweak here. |
| `src/schema.py` | Typed `Facts` / `Conclusion` / `Assessment` models (Pydantic). |
| `src/facts.py` | LLM fact extraction — the only place the model touches the assessment before gap analysis. |
| `src/rules.py` | **The rule engine.** Deterministic classification + obligations, no LLM calls. |
| `src/citations.py` | Resolves each provision cited by `rules.py` to verbatim operative text. |
| `src/gaps.py` | LLM gap assessment: pre-assesses each obligation against the client's stated architecture. |
| `src/report_v2.py` | Branded PDF generation (ReportLab). |
| `src/retriever.py` | Multilingual semantic search over the law (ChromaDB + `multilingual-e5-small`). |
| `src/ingest.py` | Chunks + embeds `knowledge/*.md` and `data/*.txt` into the local ChromaDB store. Run once, or after any law update. |
| `src/fetch_law.py` | Downloads the consolidated EU AI Act text from the Publications Office. |
| `src/scope_input.py` | Consultant-supplied Article 2 scope facts from the UI, converted into fact overrides. |
| `src/secrets_env.py` | Strips whitespace from injected env secrets — see `docs/DEPLOY.md` for the incident that made this necessary. |
| `src/limits.py` | Rate limiting, daily spend cap, auth-failure lockout. In-memory, per-instance. |
| `src/integrity.py` | Signs an `Assessment` on the way out of `/classify`, verifies it on the way back into `/chat` and `/report` — see below. |
| `src/json_extract.py` | Shared, exception-safe JSON-object/array extraction from an LLM text reply (used by `facts.py` and `gaps.py`). |
| `src/api.py` | FastAPI backend — the entrypoint. `/classify`, `/chat`, `/report`, `/health`, `/usage`. |
| `web/` | Next.js frontend — the only UI. Two route handlers proxy to the backend; no LLM calls happen client-side. |
| `knowledge/annex_i.md`, `annex_iii.md`, `obligations.md`, `prohibited_practices.md`, `gpai_checklist.md` | Curated legal reference used to ground fact extraction via RAG. |
| `eval/` | Evaluation harness — see `docs/EVALUATION.md`. |
| `tests/` | Unit tests — see the Testing section of the README. |

## End-to-end request path

**`POST /classify`** (`src/api.py:classify_endpoint`)
1. Resolve a client id from `X-Forwarded-For` (or the socket address), check the shared-password gate (`_check_password`) and the per-client rate limit.
2. Reject if `name`/`description` are blank, or `ANTHROPIC_API_KEY` isn't set, or the daily classification cap is reached.
3. `facts.extract_facts(...)` — one Claude call. Internally calls `retriever.retrieve(...)` against the local ChromaDB index to ground extraction in the actual statutory text, then returns a typed `Facts` object. Consultant-supplied `scope` and `organisation_role` overrides win over anything inferred from the description.
4. `rules.classify(facts, ...)` — pure Python, no network call. Walks the `Facts` through the deterministic decision tree (territorial scope → AI-system definition → prohibited practices → high-risk → transparency → GPAI) and returns an `Assessment`, with each `Conclusion` citing its provision via `citations.py`.
5. `gaps.assess_gaps(...)` — a second Claude call, judging each obligation the rule engine identified against the client's stated architecture/components, producing a gap-check question, assessment and status per obligation.
6. On any exception, the daily-cap counter is refunded (`limits.refund_daily()`) since the spend didn't complete, and a generic 500 is returned — provider errors and internals are logged server-side, not echoed to the caller.

One classification is therefore **two Claude calls**: step 3 and step 5.

**`POST /report`** (`src/api.py:report_endpoint`)
1. Same password/rate-limit gate.
2. `report_v2.generate_report(...)` builds the PDF into a `tempfile.TemporaryDirectory()` that is deleted as soon as the bytes are read back — the server keeps no copy of a client's report.
3. Returns the PDF bytes directly; the frontend's `/api/report` route streams them to the browser.

**Frontend** (`web/app/api/classify/route.ts`, `web/app/api/report/route.ts`, `web/app/api/chat/route.ts`) are thin proxies: they hold `BACKEND_URL` server-side (never exposed to the browser), forward the `x-app-password` header, and pass the response straight through. No Anthropic call happens in `web/`.

## Why the Assessment carries a signature

`/chat` and `/report` are stateless: the Assessment they act on travels back
from the browser as plain request JSON, not from a server-side session. That
means the client — anyone holding the shared password, editing a devtools
request — could otherwise submit an Assessment the rule engine never actually
produced, and get a chat reply or a branded PDF that treats it as real.
`/classify` signs the Assessment it returns (`assessment.sig`, an HMAC keyed
on `APP_PASSWORD`/`ASSESSMENT_SIGNING_KEY`, computed in `integrity.py`);
`/chat` and `/report` verify it before touching the payload, and reject a
mismatch with a "please re-run it" error rather than silently trusting the
edit.

## Why the LLM is not in the decision path

`facts.py` and `gaps.py` are the only two places Claude is called, and both
only ever populate structured fields (`Facts`, gap-check text) — they never
decide a tier or an obligation. `rules.py` is pure, deterministic Python that
takes a `Facts` object and returns an `Assessment`; the same input always
produces the same output, and it can be (and is) unit-tested directly without
touching the network. This is what makes `eval/` possible: the rule engine's
behavior is decidable by brute force (see `eval/completeness.py` and
`eval/coverage_matrix.py`), which would not be true if a model were making the
classification call itself.
