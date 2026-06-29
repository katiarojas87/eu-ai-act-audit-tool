# EU AI Act Audit Tool

A compliance audit tool for the EU AI Act (Regulation 2024/1689). You describe a
company's AI systems in plain language (in Dutch, French, English or Spanish), and
the tool classifies each one by risk tier (prohibited / high-risk / limited /
minimal), detects whether it triggers general-purpose AI (GPAI) obligations, maps
the legal duties that apply, pre-assesses compliance gaps from the system's
architecture, and produces a branded PDF report with deadlines and fine exposure.

Built as a LangGraph workflow combining RAG over the full legal text with
multi-step Claude reasoning and local multilingual embeddings, so client data
never leaves your machine.

## Architecture

```
Streamlit UI (app.py)
      │
      ▼
LangGraph pipeline (graph.py)
  intake → retrieve → classify → [clarify if uncertain] → obligations
      │                  │              │
      │            retriever.py    Claude Opus 4.8
      │                  │
      ▼            ChromaDB (local)
PDF report (report.py)   ▲
                   multilingual-e5 embeddings (local, free)
                         ▲
                   ingest.py  ← knowledge/*.md + data/*.txt|pdf
```

| Component | Choice | Why |
|---|---|---|
| LLM | Claude Opus 4.8 | Best legal reasoning; low volume so cost is negligible. Switch to `claude-sonnet-4-6` in `config.py` for ~2× cheaper/faster. |
| Embeddings | `multilingual-e5-large` (local) | Free, private, one shared meaning-space across NL/FR/EN/ES. |
| Vector DB | ChromaDB (local) | Zero infra; the law is small. |
| Reasoning | LangGraph | Multi-step graph with a conditional "ask the client" loop. |

## Setup

```bash
cd "EU Act"
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env            # then paste your Anthropic API key into .env

python fetch_law.py             # download the EU AI Act text into data/
python ingest.py                # build the local vector store (first run downloads the embed model)

streamlit run app.py            # launch the tool
```

## Using it in a client session

1. Enter the client/company name.
2. For each AI system the client uses, add a name + plain-language description
   (any of NL / FR / EN / ES).
3. The tool returns a risk tier (Prohibited / Annex I / Annex III / Limited /
   Minimal / GPAI), rationale, and triggering provisions. If it's uncertain it
   asks you follow-up questions and re-classifies.
4. Review obligations + gap-check questions, then export the PDF.

## Files

| File | Purpose |
|---|---|
| `config.py` | Models, paths, chunking, branding — tweak here. |
| `knowledge/annex_iii.md`, `obligations.md` | Curated legal reference (drives classification + obligations). |
| `fetch_law.py` | Downloads the regulation text. |
| `ingest.py` | Chunks + embeds documents into ChromaDB. |
| `retriever.py` | Multilingual semantic search over the law. |
| `graph.py` | The LangGraph reasoning pipeline. |
| `report.py` | Branded PDF generation. |
| `app.py` | Streamlit interface. |

## Notes
- Annex III high-risk deadline is **2 December 2027** (deferred by the Digital
  Omnibus); transparency obligations apply **2 August 2026**; GPAI since
  **2 August 2025**. Verify the curated knowledge files stay current.
- This produces a structured assessment to support compliance planning — not
  legal advice. Flag high-risk/prohibited calls for legal confirmation.
```
