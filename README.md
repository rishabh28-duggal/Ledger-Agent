# Groq edition — quick start

Groq is now available alongside Gemini and the local reader. Extract this entire ZIP into a new folder, then open PowerShell in `ap-review`. Do not run an older copy simultaneously on port 8000.

```powershell
python -m pip install -r requirements.txt
$env:GROQ_API_KEY="YOUR_KEY"
$env:GROQ_MODEL="qwen/qwen3.8-27b"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 and select Groq vision in New invoice. When a Groq key is configured, it is selected automatically. Use a fresh upload in Groq mode: Retry on an old Gemini run retains its original reader. To retain local history when moving the app, stop the old server first and copy its entire `data` directory to the new `ap-review` folder.

PDF pages (including scans) are actually rendered into JPEGs using pypdfium2 and submitted to Groq's vision model. No Poppler/OS installation is needed. This adapter supports at most THREE pages per invoice, matching the documented default model's image limit. Longer documents fail explicitly before an API call; no pages are silently omitted. All three pages are supplied in one request to preserve cross-page context. Configuring a different model does not raise this limit.

JSON mode constrains the response format but does not guarantee this invoice schema or correct extraction. Pydantic validates the resulting data, and missing evidence/low confidence triggers review. Code retains all final checks and approval decisions. Up to two retries for transient HTTP 429/5xx errors use bounded backoff. Persistent failures remain failed and do not turn into approvals. Provider error messages are shown with the configured key redacted.

The default `qwen/qwen3.8-27b` is listed in Groq's current vision documentation: https://console.groq.com/docs/vision. Availability and quota depend on your account. Set GROQ_MODEL only to a vision-capable model available in your account. Do not use text-only models for scans. Your key stays server-side. Groq receives the page images; use synthetic documents while testing. This integration has been tested with mocked API responses and actual PDF rendering, NOT a live Groq request.

Sample 09 retains its older filename `09_scan_requires_gemini.pdf`, but works with Groq vision too. Browser visual QA and hosted deployment remain outstanding. The earlier setup and workflow documentation follows below; Gemini remains an optional reader, not a requirement.

---

# Ledger — AP Invoice Review Assistant

Gemini edition of the working first version of the Zamp PS-1 solution. FastAPI + SQLite + a buildless HTML/CSS/JavaScript interface. No npm installation is required. This uses the plain-JavaScript frontend option from the plan; all financial decisions run on the server.

## Start on Windows

1. Extract the entire ZIP. Open the `ap-review` folder containing `start.bat` and `requirements.txt`.
2. Install Python 3.11 or newer if needed, with Python added to PATH.
3. Double-click `start.bat`. The first run installs dependencies and opens http://127.0.0.1:8000. If the browser opens before installation/server startup finishes, refresh it.
4. Keep the terminal open while using the application.

Alternatively, in PowerShell from this folder:

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Linux/macOS: run `sh start.sh`, then open http://127.0.0.1:8000.

## Extraction modes: an important distinction

**Local labelled-PDF reader (default):** actually extracts text from uploaded PDFs and parses the labelled fields used by the included sample documents. It does not look up fixtures, does not use an LLM, and is intentionally not a general invoice reader. This lets the workflow run without credentials. It refuses image-only scans.

**Gemini mode:** sends the uploaded PDF to the Google Gemini generateContent API, asks for schema-constrained invoice JSON, validates it with Pydantic, preserves field evidence, and routes low-confidence/missing-evidence fields to review. This supports the planned varied-layout/scan path, but has NOT been live-tested in this build because no API credential was supplied. Verify model availability for your account, configure it, then test all cases again before submission. Do not submit local-reader testing as proof of AI extraction accuracy.

PowerShell configuration before starting the server:

```powershell
$env:GEMINI_API_KEY="YOUR_KEY"
$env:GEMINI_MODEL="gemini-3.8-flash"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The key stays on the server, never in frontend code. `.env.example` documents settings; `.env` is not automatically loaded. Set environment variables in the shell or hosting dashboard. Do not paste real credentials into code or commit them.

## Demo sequence

Open **Demo documents**. Each Run review button uploads the real PDF and runs the actual pipeline.

1. Run `01_happy_60_chairs.pdf`. Expect Ready for approval. Click Approve invoice. PO-1042 now has 60/100 chairs and INR 141,600 of INR 236,000 accepted.
2. Run `02_split_50_chairs.pdf`. Expect Needs review: only 40 chairs and INR 94,400 remain. Pending invoices do not consume balance.
3. Run `03_original_duplicate.pdf`, then run it again. The repeat is Blocked and linked by original invoice ID. The original is not overwritten.
4. Run `04_near_duplicate.pdf`. Expect Possible duplicate / Needs review. It has the same vendor, date, amount and items as 03, but a different invoice number and file hash. The included near-duplicate is a text PDF variant; a re-scan should be tested separately in Gemini mode.
5. Run `06_ambiguous_po.pdf`. Expect two candidate POs. Select PO-3001 or PO-3002 and rerun. Both are genuinely eligible synthetic POs; selection should come from a purchasing record in a real workflow.
6. Run `05_missing_information.pdf`. Expect missing invoice number and total, review findings and a deterministic vendor email draft. No email is sent.
7. `09_scan_requires_gemini.pdf` is a genuine image-only PDF. Local mode fails explicitly; Gemini mode needs credentials. This is intentionally incomplete and has no readable invoice number/total.
8. `07_arithmetic_error.pdf` demonstrates correction: change total from 99999 to 23600. The original and correction remain logged. Run independently if prior PO consumption could affect the result.

All documents and company/GST identifiers are explicitly fictional and not legally valid vendor verification data. The duplicate fixture uses INR 236,000 (200 stands at INR 1,000 plus 18% tax), replacing the initial illustrative INR 245,000 so the line arithmetic is consistent.

## What is implemented

- Real PDF ingestion; file hash; PDF/page/size validation; local reader and configurable Gemini adapter.
- Persisted SQLite invoices, original extraction, revisions, audit history and genuine SSE stage events.
- Completeness, currency/date checks, trusted-identifier/name/alias vendor matching, explicit/ambiguous PO matching, deterministic line aliases.
- Decimal arithmetic, INR 1 rounding tolerance, tax calculation, tax-basis-aware unit-price comparison, separate cumulative PO quantity and value limits.
- Hash, vendor/invoice identity and near-duplicate checks. Reruns exclude themselves.
- Field/line corrections, PO selection, retry, and explicit reviewer acceptance.
- Transactional acceptance rechecks balances and is idempotent. Accepted records are immutable.
- Dashboard, PO utilisation, source PDF, evidence, reason trail and copyable email draft.
- Optional access token and explicitly enabled demo-only reset.

## Remaining before a submission-ready live demo

- Supply a Gemini key/model, live-test extraction on varied layouts and scans, and refine schema/prompts from measured results.
- Browser visual/interaction QA remains unverified: the available preview service could not launch the Python runtime. API tests and JavaScript syntax checks passed; do not treat these as browser QA.
- Deploy the Python backend on a single instance with persistent disk for SQLite AND PDFs; a static-only hosting service cannot run this stack. Dockerfile is included. This ZIP is runnable source, not an already hosted submission link.
- Optional AI-rephrased summaries and semantic item/PO suggestions are deferred. Current summaries/email drafts are deterministic and fully usable. Matching intentionally uses trusted identities and configured item aliases; unsupported ambiguity stays in review.
- Authentication is a shared demo access token, not production multi-user identity. Audit records label the reviewer "Demo reviewer".
- No goods receipts, legal GST verification, payment execution, automatic email sending, accepted-invoice reversals or duplicate overrides.

## Policies and state

System recommendation: Ready for approval / Needs review / Blocked. Reviewer disposition: Awaiting approval / Accepted. Technical status: queued / running / completed / failed. These states remain separate.

Only accepted invoices consume balances. Approval runs inside `BEGIN IMMEDIATE`, rechecks all rules, and records line allocations once. Pending duplicate requests cannot double-consume balance. Interrupted jobs become failed/retryable after server restart. Each retry/field correction/PO selection creates a new run and preserves the original extraction. Policy v1 is fixed in code; expose configuration in a future release rather than implying that the current UI edits policy.

Date policy is no future dates and a 365-day window using the server date. Production should choose a business timezone explicitly. Unit-price variance <=2% passes; >2–5% review; >5% high-severity review. A unit-price pass never overrides the PO commitment cap. Unknown vendors require review; explicitly blocked vendors block.

Inclusive-price documents whose presented subtotal/total conventions cannot be reconciled by the initial arithmetic rules go to review. No unsupported tax/discount convention is silently inferred.

## Deploy

Use a Python or Docker-capable host, one instance, and mount durable storage at `/data`. Set `AP_DATA_DIR=/data`. Configure `GEMINI_API_KEY`, `GEMINI_MODEL` and a strong `AP_ACCESS_TOKEN` in the host's environment. Set access before exposing the app. The UI's Deployment access button stores the token in sessionStorage for this tab and sends it as a bearer header, including PDF fetches and SSE requests. API records and docs require this token when configured. Keep synthetic data only on the demo service.

Build: `docker build -t ap-review .`
Start: `docker run --rm -p 8000:8000 -v ap-review-data:/data --env-file .env ap-review`

Creating an `.env` for Docker is an explicit local setup step; use `.env.example` as the template and never commit real keys. Without Docker, start with `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`. Bind to 0.0.0.0 only behind the hosting platform's HTTPS/access controls.

To enable the destructive synthetic-data reset, explicitly set `AP_DEMO_RESET=1`. It is disabled by default and the UI requires confirmation. Never enable it for real invoices. Sample dates are generated when `python scripts/make_samples.py` is run; regenerate if the policy window has elapsed.

## Verify

```sh
python -m pytest -q
```

Tests exercise real PDF uploads through the API and persisted database: happy-path acceptance, repeat approvals, split overrun, approval-time balance changes, duplicate and near-duplicate results, PO ambiguity/selection, correction/audit preservation, unsupported scans, missing fields, SSE replay, PDF access, auth, reset, aggregate quantity checks, conflicting identifiers and independent unit-price/PO-value tolerances.

Frontend syntax: `node --check app/static/app.js`. Gemini adapter tests use mocked responses to verify PDF submission, schema configuration, low-confidence handling, quota/auth errors and invalid output. No model-output accuracy claims are made by these tests.

## Get your Gemini key

Create your own key at https://aistudio.google.com/apikey. Check your project/model quota before testing; free-tier access and limits depend on the account and model. Use synthetic documents for evaluation. The default GEMINI_MODEL is gemini-3.8-flash; if it is unavailable in your account, set GEMINI_MODEL to a currently available PDF-capable model that supports structured JSON output. No live Gemini request has been made without your key.

The app sends the uploaded PDF (including scanned pages) directly to Google when Gemini mode is selected. Local mode never sends documents to an AI provider. No automatic fallback hides a Gemini failure.
