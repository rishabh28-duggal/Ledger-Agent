# Ledger

Invoice review with a clear path from document to decision. This version replaces the Streamlit interface with a responsive FastAPI web application designed for Cloud Run.

## Start here

- **Run locally:** `python app.py` after installing `requirements.txt` and Tesseract, or use Docker below.
- **Deploy to Google Cloud:** follow [docs/DEPLOY.md](docs/DEPLOY.md).
- **Rehearse the case-study demo:** follow [docs/DEMO.md](docs/DEMO.md).
- **Understand the fallback:** read [docs/FALLBACK_RULES.md](docs/FALLBACK_RULES.md).
- **See what was tested:** read [docs/VALIDATION.md](docs/VALIDATION.md).

## What you get

- A readable, responsive interface: overview, uploads, review queue, invoice detail, procurement master and explained rules.
- Username/password accounts with Argon2id password hashes and revocable server-side logins. No email address or password recovery.
- A private demo without account creation. Each visitor gets their own signed, 24-hour demo session, fictional vendors/POs and sample invoices.
- Every folder starts with its own editable vendor and PO list from the repository; their data is scoped to a fresh, random account ID on the server.
- Up to 250 PDFs/images in a browser batch, 10 MB and 30 pages per document. Files upload individually with three concurrent requests. A demo is limited to 15 invoices per session; registered sessions support 400 invoices. Start a new session to retain larger histories in separate runs.
- Gemini PDF/image extraction with independent embedded-text extraction and local Tesseract OCR fallback. Missing data never becomes invented data.
- Deterministic checks for vendor identity, POs, duplicates, quantities, arithmetic, tax basis, price tolerance, date and remaining PO authorisation.
- Original document preview/download beside editable fields, page evidence, editable line items and explicit reviewer confirmation.
- A separate human approval step with atomic PO consumption and rechecking of other open decisions.
- Saved folders, per-invoice run trails, original extraction, audited changes, vendor follow-up drafts, Excel downloads and CSV/JSON API exports.
- All-folder overview with filters, grouping, real invoice amount summaries and monthly graph; selectable bulk approval, light/dark themes and collapsible navigation.
- Private Cloud Storage, Firestore persistence and a private queued Cloud Run worker. Browser closure does not cancel hosted processing.
- Cloud Build configuration to test and redeploy both services when GitHub `main` changes.

## Local setup

Use Python 3.12. Install Tesseract separately:

- Windows: install Tesseract using an established distribution and put `tesseract.exe` on PATH, then reopen the terminal. Confirm with `tesseract --version`.
- macOS: `brew install tesseract`
- Debian/Ubuntu: `sudo apt-get install tesseract-ocr tesseract-ocr-eng`

Then:

```bash
python -m venv .venv
# Activate it using the command for your OS, then:
python -m pip install -r requirements.txt
python app.py
```

Open `http://localhost:8080` and choose **Try the demo**. The demo works without cloud credentials or an API key. `start.bat` and `start.sh` also create the environment and install dependencies.

Copy `.env.example` to `.env` if you want to configure Gemini locally. `python app.py` reads it. For direct `uvicorn cloud.main:app`, set environment variables yourself. Never commit `.env`.

A missing Gemini key falls back immediately. Local SQLite data is saved in `data/cloud`. A local server restart invalidates demo cookies unless `LEDGER_SESSION_SECRET` is configured. Local in-process tasks do not survive a restart; saved invoices can be retried. Only cloud mode uses a durable task queue.

### Docker (includes OCR)

```bash
docker build -t ledger .
docker run --rm -p 8080:8080 -v ledger-data:/app/data ledger
```

The named volume persists local data. Add `--env-file .env` if configured. This command is for local mode, not the production multi-service deployment.

## Accounts

Choose **Create account**, enter a unique username (3?32 letters, numbers, dots,
underscores or hyphens), and a password of 8?1024 characters. Numeric usernames
such as `123` and passwords such as `12345678` are accepted. Usernames are Unicode
NFKC-normalized and case-insensitive; passwords are used exactly as entered.
No email, verification service or password recovery is used.

Passwords are hashed with Argon2id through `argon2-cffi`. A login lasts 24 hours
by default (`LEDGER_LOGIN_TTL_SECONDS`, 60 seconds to 30 days). Random 256-bit
login tokens are sent only in HttpOnly, SameSite=Lax cookies; SHA-256 token hashes
and absolute expiry times are stored server-side. Logout revokes the stored login.
Cookies use Secure automatically on Cloud Run; set `LEDGER_COOKIE_SECURE=1` for
other HTTPS production deployments. Serve production only over HTTPS.

SQLite stores authentication records alongside invoice records in
`data/cloud/ledger.sqlite3`; Cloud Run stores them in server-only Firestore
collections. Registering creates a fresh account ID with no invoices. New folders receive their own vendor and PO list. Existing
Firebase-owned and demo records stay intact, but are never automatically attached
to a username. Back up storage before upgrading; any legacy ownership transfer
requires a separate, authenticated administrative migration. There is no automatic
recovery or transfer path in this version.

State-changing browser requests require a signed CSRF cookie and matching
`X-CSRF-Token` header obtained from `/api/csrf`, plus same-origin checks. Login is
limited to 10 attempts per normalized username and 60 per client IP in 15 minutes;
registration is limited to 10 attempts per IP in 15 minutes. Limits persist in the
same database and apply across instances. Only trust forwarding headers from your
hosting proxy (the provided container is intended to sit behind Cloud Run).

Real account history is separate from demo history. Uploaded invoice data is sent
to Gemini only when the Gemini reader is selected/available; local-only upload
mode skips Gemini. Firestore and Cloud Storage continue to use server IAM.

## Vendor imports

Import vendor XLSX/CSV files through a validated preview and explicit confirmation on Vendors & POs. Download the template and JSON backups from Backup & template. JSON import replaces the vendor/PO list after confirmation; spreadsheet import adds or explicitly updates vendors only. See [vendor import guide](docs/VENDOR-IMPORT.md) for limits, matching, locks and validation.

## Structure

```text
app/          Shared deterministic checks, extraction schema and next-step text
cloud/        API, authentication, storage, queue worker and fallback reader
web/          Accessible HTML, responsive CSS and browser application
samples/      Fictional procurement master and workflow PDFs
test_pack/   Additional varied-layout, missing-data and scanned fixtures
tests/       API, isolation, fallback, approval and 120-document checks
 scripts/     Local launcher, Google Cloud setup and demo cleanup
 docs/        Deployment, fallback, demo and validation guides
```

## Verification

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
node --check web/app.js
node tests/ui-render.cjs
```

Tests use local SQLite and the real installed OCR engine. They do not validate your Gemini key or Google Cloud permissions. See the validation guide for the exact verification boundaries.

## Important boundaries

This is a case-study application with deliberately visible limits. It does not move money, validate GST registrations, support arbitrary handwritten layouts, convert units/currencies, or split a single invoice across multiple POs. New sessions have independent duplicate history and PO balances. Use a single shared session for invoices that must share procurement limits.

The UI has responsive layouts, keyboard focus styles, labelled controls, dialogs and status announcements. Browser-based visual QA and live cloud/Gemini testing must be completed in the target environment before submission. Google Cloud resources and Gemini may incur charges; configure billing alerts and observe your quotas.
