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
- Login and account creation through Firebase Authentication, including password reset.
- A private demo without account creation. Each visitor gets their own signed, 24-hour demo session, fictional vendors/POs and sample invoices.
- Registered users start with an empty procurement master; their data is scoped to their verified Firebase UID on the server.
- Up to 250 PDFs/images in a browser batch, 10 MB and 30 pages per document. Files upload individually with three concurrent requests. A demo is limited to 15 invoices per session; registered sessions support 400 invoices. Start a new session to retain larger histories in separate runs.
- Gemini PDF/image extraction with independent embedded-text extraction and local Tesseract OCR fallback. Missing data never becomes invented data.
- Deterministic checks for vendor identity, POs, duplicates, quantities, arithmetic, tax basis, price tolerance, date and remaining PO authorisation.
- Original document preview/download beside editable fields, page evidence, editable line items and explicit reviewer confirmation.
- A separate human approval step with atomic PO consumption and rechecking of other open decisions.
- Saved sessions, per-invoice run trails, original extraction, audited changes, vendor follow-up drafts, CSV export and invoice JSON export.
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

Firebase web configuration enables the login/create-account controls. Backend verification uses the Firebase Admin SDK and Application Default Credentials. Configure Firebase before testing real accounts; the demo needs neither Firebase nor a public API key. No passwords are handled by Ledger's backend.

Real account history is separate from demo history. Creating an account does not migrate demo invoices automatically. Uploaded invoice data is sent to Gemini only when the Gemini reader is selected/available; local-only upload mode skips Gemini.

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
```

Tests use local SQLite and the real installed OCR engine. They do not validate your Gemini key or Google Cloud permissions. See the validation guide for the exact verification boundaries.

## Important boundaries

This is a case-study application with deliberately visible limits. It does not move money, validate GST registrations, support arbitrary handwritten layouts, convert units/currencies, or split a single invoice across multiple POs. New sessions have independent duplicate history and PO balances. Use a single shared session for invoices that must share procurement limits.

The UI has responsive layouts, keyboard focus styles, labelled controls, dialogs and status announcements. Browser-based visual QA and live cloud/Firebase/Gemini testing must be completed in the target environment before submission. Google Cloud resources and Gemini may incur charges; configure billing alerts and observe your quotas.
