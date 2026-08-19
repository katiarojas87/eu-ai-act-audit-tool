# Deploying

Backend on **Google Cloud Run** (`eu-ai-act-krs-8842`, `europe-west1`), frontend
on **Vercel**. Both already exist in your tooling.

The backend holds the Anthropic key and does the spending. The frontend holds
nothing secret except the shared password it forwards, and never talks to
Anthropic directly.

---

## 0. Secrets belong in Secret Manager, not env vars

**Resolved 2026-08.** The first deployment stored `ANTHROPIC_API_KEY` as a
plain environment variable on Cloud Run — readable by anyone with Viewer on
the project, and persisted in every revision. That key was revoked and
rotated; both secrets now live in Secret Manager as shown below. Recorded here
because it is the kind of mistake worth documenting, not repeating: if you
ever see `--set-env-vars` carrying `ANTHROPIC_API_KEY` or `APP_PASSWORD` again
in a deploy command, that is a regression, not a variant.

To do this from scratch (new project, or rotating again):

1. Revoke the old key at <https://console.anthropic.com> → API Keys.
2. Create a new one.
3. Put it in Secret Manager — never in `--set-env-vars`.

```bash
gcloud services enable secretmanager.googleapis.com --project eu-ai-act-krs-8842

# NOTE: `--data-file=-` reads stdin. Pasting and pressing Enter before Ctrl-D
# stores a TRAILING NEWLINE, which makes an illegal HTTP header — the Anthropic
# SDK then reports "APIConnectionError: Connection error", which looks like a
# network fault and sends you hunting in the wrong place. Use a hidden prompt
# and printf, which cannot add one:
read -rs -p "Paste the new key: " KEY \
  && printf %s "$KEY" | gcloud secrets create anthropic-api-key \
       --replication-policy=automatic --project eu-ai-act-krs-8842 --data-file=- \
  && unset KEY

# Choose a real password — not a word. e.g. `openssl rand -base64 24`
gcloud secrets create app-password --replication-policy=automatic \
  --project eu-ai-act-krs-8842 --data-file=-
```

Grant the runtime service account access:

```bash
PROJECT_NUMBER=$(gcloud projects describe eu-ai-act-krs-8842 --format='value(projectNumber)')
for S in anthropic-api-key app-password; do
  gcloud secrets add-iam-policy-binding $S \
    --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    --role=roles/secretmanager.secretAccessor --project eu-ai-act-krs-8842
done
```

`secrets_env.py` strips surrounding whitespace from these values at startup as a
backstop, so a stray newline degrades to a logged warning rather than an
inscrutable connection error. Store them clean anyway.

Cloud Run reads a secret when the container starts, so **a new secret version
needs a new revision**. Add the version, then force one:

```bash
printf %s "$NEW_KEY" | gcloud secrets versions add anthropic-api-key \
  --data-file=- --project eu-ai-act-krs-8842

gcloud run services update eu-ai-act-audit --project eu-ai-act-krs-8842 \
  --region europe-west1 --update-env-vars "SECRET_REV=$(date +%s)"
```

**Converting an existing plaintext env var to a secret needs two steps** — Cloud
Run refuses to change the type in place:

```bash
gcloud run services update eu-ai-act-audit --project eu-ai-act-krs-8842 \
  --region europe-west1 --remove-env-vars ANTHROPIC_API_KEY,APP_PASSWORD

gcloud run services update eu-ai-act-audit --project eu-ai-act-krs-8842 \
  --region europe-west1 \
  --set-secrets "ANTHROPIC_API_KEY=anthropic-api-key:latest,APP_PASSWORD=app-password:latest"
```

---

## 1. Backend → Cloud Run

```bash
cd "EU Act"

gcloud run deploy eu-ai-act-audit \
  --source . \
  --project eu-ai-act-krs-8842 \
  --region europe-west1 \
  --allow-unauthenticated \
  --cpu 2 --memory 2Gi \
  --max-instances 3 \
  --concurrency 10 \
  --timeout 120 \
  --set-secrets "ANTHROPIC_API_KEY=anthropic-api-key:latest,APP_PASSWORD=app-password:latest" \
  --update-env-vars "RATE_LIMIT_PER_HOUR=30,DAILY_CLASSIFY_CAP=200,MAX_AUTH_FAILURES=10"
```

`--allow-unauthenticated` is correct here: the app's own password is the gate,
because clients cannot present Google credentials. The limits are what make that
safe.

**Use `--update-env-vars`, not `--set-env-vars`, here.** `--set-env-vars`
*replaces* the whole env var list — run it on a redeploy after step 3 has
already set `FRONTEND_ORIGIN`, and it silently wipes that, breaking CORS for
the deployed frontend until someone notices. `--update-env-vars` merges
instead, so this command is safe to reuse verbatim on every redeploy, not just
the first one.

**`--max-instances 3` is a spend control, not a performance setting.** The rate
limit and daily cap live in each container's memory, so the real ceiling is the
cap × the instance count. Three instances × 200 = at most 600 classifications a
day. Raise the instances and you raise the bill.

Check it:

```bash
curl -s https://<service-url>/health | python -m json.tool
```

`/health` needs no password and reports the cap and the day's usage — use it to
see whether the tool is being hammered.

---

## 2. Frontend → Vercel

```bash
cd "EU Act/web"
vercel link          # first time only
vercel env add BACKEND_URL production      # the Cloud Run https:// URL, no trailing slash
vercel --prod
```

`BACKEND_URL` is read server-side in the route handlers, so it is never exposed
to the browser. The password is typed by the user and forwarded per request; it
is not stored in Vercel.

---

## 3. Close CORS to the real frontend

Until this step the backend accepts browser calls from `localhost:3000` only, so
the deployed frontend will be blocked. After Vercel gives you a domain:

```bash
gcloud run services update eu-ai-act-audit \
  --project eu-ai-act-krs-8842 --region europe-west1 \
  --update-env-vars "FRONTEND_ORIGIN=https://<your-app>.vercel.app"
```

Never set this to `*` — the endpoint carries client descriptions.

---

## 4. Redeploy after a law change

The corpus is a snapshot. After any amendment:

```bash
python src/fetch_law.py --list # what consolidated versions exist
python src/fetch_law.py        # take the newest
python src/ingest.py           # rebuild the vector store
pytest                         # a test fails if the corpus went stale
```

then redeploy the backend. `data/eu_ai_act.source.json` records which version is
baked into the running image.

---

## What the limits actually do

| Control | Default | Env var |
|---|---|---|
| Requests per client per hour | 30 | `RATE_LIMIT_PER_HOUR` |
| Classifications per day, per instance | 200 | `DAILY_CLASSIFY_CAP` |
| Failed passwords before lockout | 10 (15 min) | `MAX_AUTH_FAILURES` |
| Description length | 8 000 chars | — |
| Systems per report | 50 | — |

A classification is **two Opus calls** (fact extraction + gap assessment). Size
the daily cap against what you are willing to spend, and set a budget alert:

```bash
gcloud billing budgets create --billing-account=<ID> \
  --display-name="EU AI Act tool" --budget-amount=50EUR
```

The per-client rate limit keys on `X-Forwarded-For`, which a determined caller
can spoof. It bounds honest use and slows abuse; **the daily cap is the control
that actually bounds spend.**

---

## Data handling

Descriptions and component lists go to the Anthropic API for fact extraction and
gap assessment. Classification itself is local and deterministic. Reports are
generated into a temporary directory and deleted once returned — the server
keeps no copy of a client's document. The UI says all of this above the form.

If you process client data on their behalf, that is a processor relationship:
tell them where it goes before they type it.
