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

The rule engine is deterministic and unit-tested, so the place a real assessment
most easily goes wrong is fact extraction. `eval/` measures that against 80
labelled descriptions across NL/FR/EN/ES, and — because extraction is not the
only thing that can be wrong — also measures duty-set accuracy, decision
coverage, label sufficiency and the carve-out boundaries.

```bash
python eval/run_eval.py --check-labels   # offline, no API key: are the labels sound?
python eval/run_eval.py                  # full run (50 API calls)
python eval/run_eval.py --limit 5        # cheap smoke test
```

Two failure modes are scored separately, because they cost a client differently:

| Verdict | Meaning | Consequence |
|---|---|---|
| `abstained` | the model left a fact unknown | a visible gap and a follow-up question — recoverable |
| `wrong` | the model asserted something untrue | a confidently incorrect report nobody is prompted to check |

End-to-end, a tier below the true one is an **under-warning** (the client is told
they owe less than they do) and is gated hardest, at 2%.

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
compatible with a true rate up to 18%. `eval/scaffold_cases.py` computes the
shortfall exactly: **+129 tier-asserting cases**, about 189 in total.
`run_eval.py` prints `PASS` / `UNPROVEN` / `FAIL` on this basis, reports how many
further observations each unproven gate needs, and will not report an unproven
gate as met.

**Do not quote these figures without their intervals.**

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

### Dataset composition

| Set | Cases | Tier-asserting | Purpose |
|---|---|---|---|
| `golden_set.json` | 50 | 43 | Development. Tuned against, so scores on it are optimistic. |
| `holdout_set.json` | 30 | 17 | **Never tuned against.** The unbiased figure. |
| `near_miss_set.json` | 5 pairs (10) | 10 | Boundary pairs differing by one decisive fact. |
| `pending_set.json` | generated | — | Annotation stubs. Read by no scorer. |

Languages are mixed on purpose (NL / FR / EN / ES), because that is how intake
actually arrives.

### Label policy

1. **Article 2 scope gates are mandatory in every case.**
   `military_defence_national_security` (Art. 2(3)),
   `sole_purpose_scientific_research` (Art. 2(6)),
   `prerelease_research_testing` (Art. 2(8)) and
   `personal_non_professional_use` (Art. 2(10)) must be stated explicitly —
   including where the answer is an obvious `false`. Any one of them being true
   takes the system out of scope entirely and zeroes the duty list, so an
   unstated gate is not a missing detail, it is an unchecked assumption that the
   Regulation applies. `run_eval.py --check-labels` fails on a case that omits
   one.
2. **`null` means the description genuinely does not say.** It is a legitimate
   label, not a default, and it scores as an abstention rather than an error.
3. **Labels describe the description, not the desired answer.** A case is
   written first and labelled second.
4. **A case may only assert a `tier` that the rule engine actually reaches from
   its labelled facts** — verified offline by `--check-labels`.
5. **Held-out discipline:** do not change `facts.py` in response to a holdout
   failure without first reproducing it in the development set, and never move
   cases between the two.

### Is the eval set good enough to support the claim?

Four checks, all offline and free. They exist because "we scored the fields we
chose to label" is the first thing a hostile reader attacks, and none of it is a
matter of opinion — `rules.py` is deterministic, so sufficiency and coverage are
decidable by brute force.

```bash
python eval/completeness.py --set holdout    # do the labels pin the answers?
python eval/coverage_matrix.py --both        # what does the set never test?
python eval/coverage_matrix.py --branches    # which lines of rules.py it reaches
python eval/near_miss_tests.py               # do the boundaries actually bite?
python eval/obligations.py --metrics         # duty recall / precision / F2
python eval/scaffold_cases.py                # how much annotation is outstanding
```

**Label sufficiency** (`completeness.py`) perturbs every *unlabelled* field
across every value it could take and re-runs the engine. If the tier, roles or
duty set moves, that field was decisive and the case does not pin its own
answer.

Normalised per case, because the set grew at the same time:

| Development set | Before scope gates (42 cases) | Now (50 cases) |
|---|---|---|
| Unlabelled-but-decisive instances | 850 — **20.2/case** | 794 — **15.9/case** |
| …that would move the tier | 513 — **12.2/case** | 416 — **8.3/case** |
| Cases stating all 4 scope gates | 0/42 | **50/50** |

Across both scored sets, **80/80 cases** state every Article 2 gate, enforced by
`run_eval.py --check-labels`.

No case is yet *fully* pinned. The remaining flags are concentrated in the
Art. 5 prohibition triggers, and closing them involves a real trade-off: the
engine already treats a context-irrelevant prohibition as "clear" when unknown,
so a model that abstains on "does this CV screener generate CSAM?" is behaving
correctly — but labelling the field `false` would score that correct abstention
as a miss and depress field accuracy. Resolving that means deciding whether
abstention on an inapplicable prohibition should count against the score. It is
a live methodological question, not an oversight.

**Decision-space coverage** (`coverage_matrix.py`): **59/59 situations (100%)**
across both sets — every tier, role, Annex III domain, GPAI relationship, Art. 5
prohibition and carve-out is exercised by at least one case. `--branches`
reports **80% of `rules.py` lines** reached. Coverage is not depth: several
prohibitions still rest on a single case, so "covered" means "tested once", not
"tested well".

**Near-miss boundaries** (`near_miss_tests.py`): five pairs that differ by
exactly one decisive fact, asserting isolation (only that fact differs),
sensitivity (the outcome moves in the documented dimension) and invariance
(facts the boundary does not depend on leave the tier alone). **5/5 hold.**

| Pair | Decisive fact | a → b |
|---|---|---|
| Motor vs health insurance | `insurance_life_or_health` | MINIMAL → ANNEX_III |
| Badge reader vs watchlist | `biometric_verification_only` | MINIMAL → ANNEX_III |
| Fraud vs creditworthiness | `credit_fraud_detection_only` | MINIMAL → ANNEX_III |
| Police vs judicial | `high_risk_domains` | same tier, **different article** |
| GPAI model vs product | `gpai_relationship` | same tier, **different duties** |

The last two share a tier deliberately: the tier metric cannot see them, which
is the argument for having pairs at all.

**Obligation metrics** (`obligations.py --metrics`) score the thing a client
actually receives. Duties are keyed `role:article` — `deployer:Art. 27` and
`provider:Art. 27` are different claims about the law and never collapse.
Reported as recall, precision, F1 and **F2** (recall weighted 4×, because a duty
omitted is a compliance gap while a duty added merely wastes money), plus
under-warning and over-warning rates, broken down by role, article and tier.
Against the frozen baseline: 389 duties across 50 cases, no omissions.

**That measures drift, not correctness** — the baseline was generated by the
engine, so a perfect score proves the engine has not changed, not that it is
right. `eval/obligation_baseline.json` becomes a correctness metric the moment
counsel reviews and corrects it, and it is the artefact they can review without
reading the schema.

During a real run (`run_eval.py`), obligation metrics are computed end-to-end:
duties implied by the *labelled* facts versus duties produced from the
*extracted* facts. That is where a field error either does or does not change
what someone is told to do.

### How much evidence is still missing

`eval/scaffold_cases.py` turns the unproven gates into a case count:

```
tier_exact           target  85%   +0 tier-asserting cases
tier_under_warned    target   2%   +129 tier-asserting cases
```

About **189 tier-asserting cases** in total are needed to demonstrate the 2%
under-warning ceiling; there are **60**. `--count N` writes annotation stubs to
`pending_set.json` with every required field present and nulls to fill. It does
not invent descriptions or labels: a fabricated case raises `n` and lowers the
evidence, which is the opposite of the point.

### Human review policy

`human_review_required` is set by the engine, not by the operator, and the PDF
prints it as a visible banner with the reason — not as a JSON field. It is true
whenever any of these hold:

- the tier is `PROHIBITED`, `ANNEX_I`, `ANNEX_III` or `UNDETERMINED`;
- a prohibition is possible or triggered-but-conditional;
- an Art. 6(3) derogation is claimed (a claimed exemption must be checked);
- confidence is `low`.

Every high-risk and prohibited determination is therefore review-gated by
construction. The report also states its methodology and its unmodelled areas,
because a disclosed limit is a professional judgment and an undisclosed one is a
misrepresentation.

### What this evaluation does NOT establish

- **It does not establish legal certainty.** It measures whether the tool reads
  a description consistently and applies a fixed reading of the Act. Whether
  that reading is correct is a legal question these numbers cannot answer.
- **It does not resolve ambiguous provisions.** Where the Act admits more than
  one reading, the engine applies one and flags it. Reasonable practitioners
  disagree about Art. 6(3) scope, what "substantial modification" means under
  Art. 25(1), and the edge of Annex III(5)(c) — the eval scores consistency with
  *our* reading, not correctness against a settled one.
- **There is no external ground truth.** Every case and every unit test encodes
  one person's interpretation. `tier_exact` largely re-tests extraction, because
  the engine is deterministic. The two things that would change this: worked
  examples from the Commission's own guidelines converted into cases, and blind
  dual annotation by an EU AI Act lawyer with agreement measured (Cohen's κ) on
  tier, role and duty set.
- **Three of four gates are statistically unproven** (see the table above). Only
  field accuracy is demonstrated.
- **Incomplete modelling.** Administrative fines (Art. 99) are not modelled at
  all. Downstream GPAI provider duties beyond the Art. 3(68) distinction are not
  fully modelled. National implementing law is out of scope.
- **Coverage is breadth, not depth.** 59/59 situations means each is touched at
  least once; several rest on a single case.

This supports compliance *planning*. It is not an accuracy claim, not a
conformity assessment under Art. 43, and not evidence of compliance for any
authority.

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
| `eval/completeness.py` | Label sufficiency + Article 2 scope-gate validation. |
| `eval/coverage_matrix.py` | Decision-space + line coverage of the rule engine. |
| `eval/obligations.py` | Duty-set metrics, review baseline, drift gate. |
| `eval/near_miss_tests.py` | Boundary pairs: one fact changes the legal outcome. |
| `eval/scaffold_cases.py` | How much annotation is outstanding; writes stubs. |
| `test_*.py` | Unit tests — run `pytest` (304, no API key needed). |

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
