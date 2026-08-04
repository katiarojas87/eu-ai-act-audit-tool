# EU AI Act Audit Tool

A compliance audit tool for the EU AI Act (Regulation 2024/1689). You describe a
company's AI systems in plain language (in Dutch, French, English or Spanish), and
the tool classifies each one by risk tier (prohibited / high-risk / limited /
minimal), detects whether it triggers general-purpose AI (GPAI) obligations, maps
the legal duties that apply with their deadlines, pre-assesses compliance gaps
from the system's architecture, and produces a branded PDF report that quotes the
provision behind every conclusion.

**The LLM never decides the classification.** It only extracts structured facts
from the description; a deterministic Python rule engine (`rules.py`) applies the
law to those facts. That is what makes the result reproducible, unit-testable,
and traceable to a specific article.

### Data handling

Embeddings and the vector store are local. **The system description and component
list are sent to the Anthropic API** for fact extraction (`facts.py`) and gap
assessment (`gaps.py`) — client data does leave the machine. Tell clients this,
and avoid pasting personal data into descriptions.

## Architecture

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

| Component | Choice | Why |
|---|---|---|
| LLM | Claude Opus 4.8 | Best legal reasoning; low volume so cost is negligible. Switch to `claude-sonnet-4-6` in `config.py` for ~2× cheaper/faster. |
| Embeddings | `multilingual-e5-small` (local) | Free, private, one shared meaning-space across NL/FR/EN/ES. `e5-large` is marginally better if you have the disk. |
| Vector DB | ChromaDB (local) | Zero infra; the law is small. |
| Classification | Plain Python (`rules.py`) | Deterministic, testable, and citable — no model in the decision path. |

## Setup

**Backend** (rule engine + RAG + PDF):

```bash
cd "EU Act"
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env            # then paste your Anthropic API key into .env

python fetch_law.py             # download the EU AI Act text into data/
python ingest.py                # build the local vector store (first run downloads the embed model)

APP_PASSWORD=yourpassword uvicorn api:app --port 8090
```

**Frontend** (the only UI):

```bash
npm --prefix web install
npm --prefix web run dev        # http://localhost:3000
```

`web/.env.local` needs `BACKEND_URL=http://localhost:8090` and the same
`APP_PASSWORD`. The backend refuses to start serving without `APP_PASSWORD` set
— use `ALLOW_NO_PASSWORD=1` for local work.

Run the tests with `pytest` (they need no API key — the rule engine is pure Python).

## Evaluation

The rule engine is deterministic and unit-tested, so the only place a real
assessment can go wrong is fact extraction. `eval/` measures that against 42
labelled descriptions across NL/FR/EN/ES (`eval/golden_set.json`).

```bash
python eval/run_eval.py --check-labels   # offline, no API key: are the labels sound?
python eval/run_eval.py                  # full run (42 API calls)
python eval/run_eval.py --limit 5        # cheap smoke test
```

Two failure modes are scored separately, because they cost a client differently:

| Verdict | Meaning | Consequence |
|---|---|---|
| `abstained` | the model left a fact unknown | a visible gap and a follow-up question — recoverable |
| `wrong` | the model asserted something untrue | a confidently incorrect report nobody is prompted to check |

End-to-end, a tier below the true one is an **under-warning** (the client is told
they owe less than they do) and is gated hardest, at 2%.

Latest run — `eval/last_run.json`:

| Metric | Result | Target |
|---|---|---|
| Field accuracy | 96.8% (151/156) | ≥ 90% |
| Wrong assertions | 0.0% | ≤ 5% |
| Tier exact | 94.3% (33/35) | ≥ 85% |
| Under-warned | 0.0% | ≤ 2% |

**Read these as development-set numbers, not an unbiased estimate.** The prompt
was tightened in response to failures in this same set, so it is tuned on the
data it is scored against. A held-out set is needed for a true figure.

Known from the last run: after the domain prompt was tightened, the model tends
to return an empty `high_risk_domains` for carve-out cases (a badge reader, fraud
detection, motor insurance) rather than naming the domain and setting the
carve-out flag. The tier is unaffected, but the report loses the explanation —
it can no longer say "biometrics, but excluded by Annex III(1)(a)".

## Using it in a client session

1. Enter the client/company name.
2. For each AI system, add a name + plain-language description (NL / FR / EN / ES)
   and, optionally, the components/architecture.
3. **Set the client's role** if you know it (provider / deployer / …). The
   override beats inference, and it decides which obligations they get — a
   deployer owes no CE marking.
4. The tool returns a tier, a classification matrix citing the provision behind
   each conclusion, and obligations grouped by role. Facts it could not establish
   are listed as missing evidence rather than guessed.
5. Review the gap-check questions, then export the PDF.

## Files

| File | Purpose |
|---|---|
| `config.py` | Models, paths, chunking, branding — tweak here. |
| `schema.py` | Typed `Facts` / `Conclusion` / `Assessment` models. |
| `facts.py` | LLM fact extraction — the only place the model touches the assessment. |
| `rules.py` | **The rule engine.** Deterministic classification + obligations. |
| `citations.py` | Resolves each provision to verbatim operative text. |
| `gaps.py` | LLM gap assessment against the client's architecture. |
| `report_v2.py` | Branded PDF generation. |
| `knowledge/annex_iii.md`, `obligations.md` | Curated legal reference used to ground extraction. |
| `fetch_law.py` | Downloads the regulation text. |
| `ingest.py` | Chunks + embeds documents into ChromaDB. |
| `retriever.py` | Multilingual semantic search over the law. |
| `api.py` | FastAPI backend for the frontend. |
| `web/` | **The frontend** — Next.js. The only UI. |
| `test_rules.py`, `test_citations.py` | Unit tests — run `pytest`. |

## Notes

- **Application dates are hardcoded in `rules.py` and are the one piece of legal
  content in this tool that carries no citation.** The Regulation as adopted
  (Art. 113) sets Annex III high-risk at 2 August 2026 and Annex I at
  2 August 2027; the values here (2 December 2027 / 2 August 2028) assume the
  Digital Omnibus deferral. **Verify against the current consolidated text
  before sending a report to a client**, and update `DATE_*` in `rules.py`.
- **Obligations are split by role.** The Act assigns duties by role, so the tool
  derives the role from observable facts (Art. 3(3)–(7)) rather than asking the
  model to apply a legal label, and escalates to provider under Art. 25(1) where
  the client rebrands, substantially modifies or repurposes a bought system. One
  organisation can hold several roles for one system — building a tool and using
  it in-house makes you provider *and* deployer. Set the role explicitly in the
  UI when you know it; the override beats inference. Where the role cannot be
  established, both lists are shown, clearly labelled as non-cumulative.
- **Article 5 bans are qualified, not absolute.** Each prohibition carries its
  statutory elements (5(1)(a)/(b) significant harm, 5(1)(c) detrimental
  treatment) and its express exceptions (5(1)(d) human assessment on objective
  facts, 5(1)(f) medical/safety, 5(1)(g) lawful dataset filtering). Real-time
  remote biometric identification is treated as restricted rather than banned:
  with an Art. 5(1)(h)(i)–(iii) objective *and* the Art. 5(3) prior
  authorisation it is lawful, and the tool then lists the Art. 5(2)–(5)
  safeguards. Where an element or exception is unresolved the finding is
  **conditional** and the report says "suspend and confirm", never "cease
  immediately" — shutting down a lawful system is the costliest error this tool
  could make.
- **Territorial scope is checked first (Art. 2).** A system with no EU nexus, or
  caught by a carve-out — military/defence/national security (2(3)), sole-purpose
  scientific research (2(6)), pre-market research and testing (2(8), but *not*
  real-world testing), purely personal non-professional use (2(10)) — is reported
  as `OUT_OF_SCOPE` with no obligations. Where scope cannot be established the
  tool does **not** quietly exclude the system: it assumes the Regulation applies,
  continues the assessment, and lists the scope question as missing evidence.
  The classification matrix still shows the underlying tier, so you can see what
  the system *would* be if it entered the EU market.
- **The Annex III domains are narrower than their labels.** `insurance` engages
  Annex III(5)(c) only for life and health cover; `credit` excludes fraud
  detection (5(b)); `biometrics` excludes verification whose sole purpose is
  confirming a claimed identity (1(a)). Without these, motor-insurance pricing
  and office badge readers come back high-risk.
- **Article 50 duties carry their own exceptions**: 50(1) obviousness, 50(2)
  assistive/standard editing, 50(4) editorial responsibility, and the
  law-enforcement carve-out running through 50(1)–(4). An evidently artistic,
  satirical or fictional work *limits* the 50(4) duty to a disclosure that does
  not hamper enjoyment — it does not remove it.
- Known coverage gaps, deliberately not faked: GPAI downstream-provider roles and
  fine exposure (Art. 99) are not yet modelled. The report does not mention fines.
- This produces a structured assessment to support compliance planning — not
  legal advice. Flag high-risk/prohibited calls for legal confirmation.
```
