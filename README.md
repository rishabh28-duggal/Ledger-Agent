# Ledger — AP Invoice Review Assistant

Streamlit application for invoice-to-PO review, with Groq vision extraction, evidence, deterministic checks and explicit reviewer approval. Ready to deploy from this repository to Streamlit Community Cloud.

## Deploy on Streamlit Community Cloud

1. Open https://share.streamlit.io and choose **Create app**.
2. Repository: `rishabh28-duggal/Ledger-Agent`.
3. Branch: `main`.
4. Main file path: `streamlit_app.py`.
5. In **Advanced settings**, choose Python **3.12** and add secrets:

```toml
GROQ_API_KEY = "YOUR_GROQ_KEY"
GROQ_MODEL = "qwen/qwen3.8-27b"
```

6. Deploy. The platform installs `requirements.txt` automatically. No separately hosted FastAPI server is needed for this interface.
7. Use Community Cloud's app sharing settings to enable public viewing if desired. If you configure the optional `AP_ACCESS_TOKEN` secret, visitors must also enter that demo access code.

Never put real API keys in GitHub. For local Streamlit use, the same values can go in `.streamlit/secrets.toml`, which is ignored. Gemini is an optional alternative via `GEMINI_API_KEY` and `GEMINI_MODEL`; local sample mode needs no API credentials.

## Local run

```powershell
python -m pip install -r requirements.txt
$env:GROQ_API_KEY="YOUR_KEY"
$env:GROQ_MODEL="qwen/qwen3.8-27b"
python -m streamlit run streamlit_app.py
```

Or use `start.bat` / `start.sh` after configuring your server-side key. Streamlit normally opens http://localhost:8501.

## How the workflow works

Upload a PDF, select Groq vision, and click **Start review**. Actual stages update live: ingest, extract, completeness, vendor identification, PO matching, rule checks and recommendation. Results include the source PDF, field evidence, check findings and a vendor-email draft for review/copying. Nothing sends email or moves money.

AI extracts values. Code decides the recommendation using decimal arithmetic, rounding and price tolerances, line mappings, currency/date checks, vendor status, duplicates, accepted quantities and authorised monetary balances.

The automated recommendation (Ready for approval / Needs review / Blocked) is separate from reviewer acceptance. Click **Approve invoice** on a ready invoice to consume PO balance. Acceptance rechecks current balances in a transaction and records consumption once. Accepted records are read-only. Field corrections and PO selections are logged and run validation again.

## Public demo state and storage

Each Streamlit browser session has a separate SQLite database and uploaded PDFs in a temporary server directory. Visitors' balances and invoices are isolated; they do not share a global queue. Session history survives normal interactions in that session but can disappear after refresh, disconnect, server restart or redeployment. Download **Export review records (JSON)** before leaving and download source PDFs separately as needed. The export is a record snapshot, not a restore facility.

Community Cloud local storage is not durable production storage. This is an interview/demo deployment. Shared persistent AP history across sessions/restarts requires an external transactional database and durable object storage. The UI states this limitation explicitly.

Each workspace allows 30 submissions; **Show demo reset → Reset my workspace** removes that session's history and PDFs. It does not affect other sessions or remove source samples. Use synthetic documents for public demos. Configuring the provider key makes the public service use the owner's API quota.

## Demo sequence

Open **Demo documents**, select the intended reader, then run:

1. `01_happy_60_chairs.pdf` → Ready for approval. Click **Approve invoice**. PO-1042 should show 60/100 chairs and ₹141,600 accepted against ₹236,000.
2. `02_split_50_chairs.pdf` → Needs review: only 40 chairs and ₹94,400 remain.
3. Upload the first PDF again → Blocked duplicate. Reruns of the original do not duplicate themselves.
4. `06_ambiguous_po.pdf` → choose between two POs and rerun; a valid selection passes the remaining checks.
5. `05_missing_information.pdf` → missing number/total, Needs review and an email draft.
6. `09_scan_requires_gemini.pdf` → image-only PDF; despite its older filename, Groq reads it too. Missing/unreadable fields go to review.
7. `03_original_duplicate.pdf` followed by `04_near_duplicate.pdf` → possible duplicate requiring review.

The duplicate fixture uses ₹236,000 so its line arithmetic is consistent. All company names and GST identifiers are synthetic test data.

## Reader limits

- **Groq vision:** renders each page to a JPEG, sends all pages together to `qwen/qwen3.8-27b`, uses JSON mode and validates with Pydantic. Up to **3 pages**; larger documents fail before submission and are never silently truncated. Requires `GROQ_API_KEY`; `GROQ_MODEL` can select another compatible vision model available to your account.
- **Gemini:** sends the PDF directly; up to 20 pages. Requires its own key and account/model capacity. Default is `gemini-3.8-flash` because 2.5 Flash is unavailable to new users.
- **Local:** real PDF text parsing for the included labelled text invoices only. It is not AI extraction or general invoice OCR. Scans fail explicitly.

Model confidence is self-reported, not calibrated. Missing critical-field evidence and low confidence trigger review. Groq error handling distinguishes quota/auth failures, truncated output, malformed JSON and invalid schema fields. No model is allowed to approve an invoice. Provider availability and extraction accuracy still require live testing.

## Policies and limits

Single company, INR, two-way invoice/PO matching. No goods receipts or delivery verification. Trusted vendor/PO masters. Up to ₹1 arithmetic rounding; absolute unit-price variance <=2% passes, >2–5% requires review, >5% high-severity review. Quantity and PO-value caps remain separate. Policy settings are in code. Dates use the server date and a 365-day window.

Initial matching uses trusted identifiers, configured vendor aliases and line aliases. Unsupported item mappings, units, bundled items and unclear tax conventions stay in review. No legal GST verification, accepted-invoice reversals, duplicate overrides, model learning or payment execution. Reviewer identity is labelled Demo reviewer.

## Existing FastAPI interface

The original HTML interface and HTTP endpoints remain available for local development:

```sh
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Its database defaults to `data/review.sqlite3` (override via `AP_DATA_DIR`). Unlike the Streamlit session workspaces, this is a shared installation-level database. The retained Dockerfile runs this original FastAPI interface. A persistent disk is required for durable data there. Streamlit reuses the same processing, rule checks and approval code in-process without launching a second server.

## Tests

```sh
python -m pytest -q
```

Tests include API workflows, PDF rendering, mocked model responses, duplicate handling, approval races/idempotency, isolated Streamlit workspaces, live local-reader review/acceptance/overrun through Streamlit AppTest, PO selection and field corrections. Model tests do not call paid APIs or establish extraction accuracy. Browser visual QA and live Community Cloud deployment must still be checked after deployment.

The `samples/master.json` purchasing data and sample PDFs are versioned. Runtime `data/`, caches, databases and secret files are excluded. Removing mistakenly committed runtime files from the current branch does not erase earlier Git history.

## Realistic extraction fixtures

The [realistic test pack](test_pack/README.md) includes seven PDFs across three layouts, a two-page invoice, an image-only scan and an independent [answer key](test_pack/answer_key.json). In Streamlit, choose Demo documents -> Document set -> Realistic extraction test pack. Use an AI reader and the stated workspace setup. Never send the answer key to the extraction model.

## Verify a correct value without changing it

When the model flags a present field as uncertain, open the invoice and use **Verify uncertain fields**. Compare the displayed values with the PDF, select only the fields you checked, tick the source-confirmation checkbox, then choose **Confirm selected fields & rerun**. The recorded values stay unchanged. Only selected uncertainty flags are cleared; the original extraction, model confidence and human verification are preserved in the audit history. Every arithmetic, identity, duplicate, quantity and PO-value check runs again. This action does not approve the invoice or consume PO balance. Missing values require correction, accepted records remain read-only, and stale review runs cannot be verified. The retained HTML interface exposes the same action.
