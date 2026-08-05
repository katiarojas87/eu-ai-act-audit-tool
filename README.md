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

Two sets:

| Set | Cases | Purpose |
|---|---|---|
| `golden_set.json` | 42 | Development. Used to diagnose and fix extraction, so scores on it are optimistic. |
| `holdout_set.json` | 20 | **Never tuned against.** The honest figure. |

```bash
python eval/run_eval.py --set holdout
```

Held-out run (`eval/holdout_run.json`) — 30 cases. **Every rate is reported with
a Wilson 95% interval and its denominator**, because a point estimate from ~100
observations is not a measurement and quoting it as one is the fastest way to
lose an argument with someone who checks:

| Metric | Held-out (95% CI) | Target | Verdict |
|---|---|---|---|
| Field accuracy | **97.1%** (91.9–99.0%, n=104) | ≥ 90% | **pass** — interval clears the gate |
| Wrong assertions | **1.0%** (0.2–5.2%, n=104) | ≤ 5% | *unproven* — interval crosses 5% |
| Tier exact | **100%** (81.6–100%, n=17) | ≥ 85% | *unproven* — interval reaches 81.6% |
| Under-warned | **0.0%** (0–18.4%, n=17) | ≤ 2% | *unproven* — 0/17 cannot show 2% |

Only field accuracy is actually demonstrated. The other three are consistent
with the targets but do not establish them: 0 under-warnings out of 17 is
compatible with a true rate up to 18%, and showing ≤ 2% needs on the order of
150 clean tier-asserting cases. `run_eval.py` prints `PASS` / `UNPROVEN` /
`FAIL` on this basis and will not report an unproven gate as met.

**Do not quote these figures without their intervals.**

Discipline for the held-out set: do not change `facts.py` in response to a
failure there without first reproducing it in the development set, and never
move cases between the two.

Ten cases (`ho2-`) were added after the Art. 5(1)(ba)/(bb) prohibitions were
modelled, so those paths were measured cold: 39/40 fields correct, and all nine
prohibition cases classified correctly first time — the nudify app prohibited,
the safeguarded general-purpose image model not, content moderation and
authorised forensic use not.

The single wrong answer is a label ambiguity worth knowing about rather than a
model error: a company that builds its own portal on a bought model but uses it
only internally is neither cleanly `integrates_distributes` (they distribute
nothing) nor `uses_api` (they built a system around it). Left unresolved rather
than tuned away.

### Is the eval set good enough to support the claim?

Three checks answer that, all offline and free. They exist because "we scored
the fields we chose to label" is the first thing a hostile reader attacks, and
none of it is a matter of opinion — `rules.py` is deterministic, so sufficiency
and coverage are decidable by brute force.

```bash
python eval/completeness.py --set holdout    # do the labels pin the answers?
python eval/coverage_matrix.py --both        # what does the set never test?
python eval/coverage_matrix.py --branches    # which lines of rules.py it reaches
python eval/obligations.py --check           # has the duty set drifted?
```

**Label sufficiency** (`completeness.py`) perturbs every *unlabelled* field
across every value it could take and re-runs the engine. If the tier, roles or
duty set moves, that field was decisive and the case does not pin its own
answer. Current state: **0 of 42 development cases are fully pinned**, with 850
unlabelled-but-decisive field instances, 513 of which would move the tier. Those
are facts the model could get wrong with nothing in the scorecard noticing. The
tool ranks them, so labelling effort goes where it changes outcomes.

**Decision-space coverage** (`coverage_matrix.py`) reports which legally
meaningful situations the set exercises — every tier, role, Annex III domain,
Art. 5 prohibition and carve-out. Currently **51/59 across both sets**, and
**80% of `rules.py` lines** are reached. Never tested: the `distributor` role,
the `UNDETERMINED` tier, `exploits_vulnerabilities`, CSAM generation,
`art_6_3_ground`, the law-enforcement carve-out, lawful dataset filtering, and
`depicted_person_consented`. Several prohibitions rest on a single case.

**Obligation baseline** (`obligations.py`) scores the thing a client actually
receives. Field accuracy measures an intermediate; the deliverable is a duty
list, and a correct `ANNEX_III` tier that silently drops the Art. 27 FRIA scored
as a flawless result before this existed. Duties are keyed `role:article`
(`deployer:Art. 27` and `provider:Art. 27` are different claims about the law),
frozen to `eval/obligation_baseline.json`, and `--check` fails on drift. Because
it runs on the *labelled* facts it isolates the rule engine from extraction: any
difference is the engine's reading of the law. **That file is the artefact
counsel can review without reading the schema** — the cheapest route to the
external ground truth this project still lacks.

### What the eval does not establish

Every test in `test_rules.py` encodes one person's reading of the Act. They
prove the engine is self-consistent, not that it is right, and `tier_exact`
largely re-tests extraction because the engine is deterministic. There is no
external ground truth here yet. The two things that would change that: worked
examples from the Commission's own guidelines converted into cases, and blind
dual annotation by an EU AI Act lawyer with agreement measured (Cohen's κ) on
tier, role and duty set. Until then this supports compliance *planning* and is
not an accuracy claim.

## Using it in a client session

1. Enter the client/company name.
2. For each AI system, add a name + plain-language description (NL / FR / EN / ES)
   and, optionally, the components/architecture.
3. **Set the client's role** if you know it (provider / deployer / …). The
   override beats inference, and it decides which obligations they get — a
   deployer owes no CE marking.
4. **Open "Scope (Art. 2)" and set what you know.** Clients rarely say "our
   output is not used in the EU" or "this is still pre-market testing", so
   without this an out-of-scope system is never identified as one. Anything left
   untouched is inferred from the description, not assumed false.
5. The tool returns a tier, a classification matrix citing the provision behind
   each conclusion, and obligations grouped by role. Facts it could not establish
   are listed as missing evidence rather than guessed.
6. Review the gap-check questions, then export the PDF.

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
| `scope_input.py` | Consultant-supplied Art. 2 scope facts from the UI. |
| `eval/` | Golden set + scorer for fact-extraction accuracy. |
| `eval/completeness.py` | Label sufficiency — do the labels pin the answers? |
| `eval/coverage_matrix.py` | Decision-space + line coverage of the rule engine. |
| `eval/obligations.py` | Duty-set review and regression baseline (counsel-reviewable). |
| `test_*.py` | Unit tests — run `pytest` (282, no API key needed). |

## Notes

- **The corpus is the CONSOLIDATED text, not the 2024 original.** `fetch_law.py`
  discovers the latest consolidated version of Regulation (EU) 2024/1689 from
  the Publications Office and verifies it before replacing `data/eu_ai_act.txt`;
  the version fetched is recorded in `data/eu_ai_act.source.json`. This matters:
  the Digital Omnibus on AI ([Regulation (EU) 2026/1744](https://eur-lex.europa.eu/eli/reg/2026/1744/oj/eng),
  OJ L, 2026/1744, 24.7.2026) rewrote Article 4 and deferred both high-risk
  deadlines, so the original text no longer states the law. Re-run
  `python fetch_law.py && python ingest.py` after any amendment;
  `--list` shows available versions.
- **Application dates are quoted, not asserted.** They now resolve verbatim from
  Art. 113 like any other provision: Annex III high-risk **2 December 2027**,
  Annex I **2 August 2028** (Art. 113(c)), transparency 2 August 2026, and
  Chapters I–II (prohibitions, Art. 4) 2 February 2025. The PDF prints the
  clause behind the deadline.
- The Omnibus also **weakened Art. 4** — the duty is to "take measures to support
  the development of AI literacy" and expressly does not require guaranteeing any
  specific level — and gave providers of generative systems already on the market
  before 2 August 2026 a four-month transitional period for the Art. 50 marking
  duty. Both are reflected in the obligation text.
- **GPAI duties follow the model, not the product.** Art. 53 binds providers of
  general-purpose AI *models*. A company shipping a product built on someone
  else's model is a downstream provider (Art. 3(68)) and owes none of it — the
  tool says so explicitly rather than handing them the model-maker's list.
  Systemic risk is presumed above 10^25 FLOP (Art. 51(2)), the free and
  open-source exemption lifts Art. 53(1)(a)-(b) unless systemic (Art. 53(2)),
  and third-country model providers need an authorised representative (Art. 54).
- **The prohibitions inserted by the Omnibus are modelled.** Art. 5(1)(ba)
  (realistic intimate or sexually explicit imagery of an identifiable person
  without their explicit consent) and Art. 5(1)(bb) (child sexual abuse material
  within Directive 2011/93/EU) apply from **2 December 2026**. Art. 5(1a) gates
  both, and asks a *different question by role*: a provider is caught where
  generating such material is the system's intended purpose, or a reasonably
  foreseeable and reproducible outcome that adequate technical safeguards do not
  prevent; a deployer only where they use the system for that purpose. Art. 5(1b)
  excludes manipulation that neither increases exposure of intimate parts nor
  alters the nature of sexually explicit activity. Screening is gated on the
  system being generative, so a spam filter is never asked.
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
