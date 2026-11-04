# Ledger — invoice review with saved demo sessions

The final feature interface is **Streamlit** (`streamlit_app.py`). The original FastAPI/HTML interface remains available for compatibility, but the saved-session browser, scorecard and batch screens are in Streamlit.

## Start locally

```powershell
python -m pip install -r requirements.txt
$env:GROQ_API_KEY="YOUR_KEY"
$env:GROQ_MODEL="qwen/qwen3.8-27b"
python -m streamlit run streamlit_app.py
```

Open http://localhost:8501. Alternatively set server-side keys in `.streamlit/secrets.toml` (ignored by Git). Never commit keys. Optional `AP_ACCESS_TOKEN` adds an access-code gate.

## Saved review sessions

Use **New session name → Start new session** in the sidebar. Every session has its own SQLite database, vendor/PO snapshots, uploaded PDFs, approvals, audit history, scorecard and last-batch results. Previous sessions are preserved and can be reopened from **Saved review sessions**. Duplicate checks and consumed PO quantities/amounts are scoped to the selected demo session. Uploading the same PDF in a different session starts a separate test; uploading it twice in one session still triggers duplicate checks.

Bookmark the URL including its `history` parameter. This random capability key reopens your collection after browser refresh or application restart. Anyone holding that history URL can access the collection: do not share private history URLs publicly. Different visitors without the same capability get independent collections. It is a demo capability system, not production user authentication. All users still consume the configured server provider quota.

Archives default to `data/archive`. Set `LEDGER_ARCHIVE_DIR` to an absolute durable directory to put them elsewhere. Local records survive application restarts while that directory is retained. **Streamlit Community Cloud local storage is ephemeral**: these files are not guaranteed across reboots/redeployments. Use a host with a persistent volume for persistent history. External database/object-storage integration is not included. Export records before leaving an ephemeral deployment. Do not mistake session state for durable cloud storage.

No reset is needed to repeat the demo. Start a new session instead. Existing archives are never silently deleted.

## Import invoices from the previous FastAPI installation

Stop the old server first. Keep its `data` folder. In the new project run:

```powershell
python scripts/import_history.py --source "E:\path\to\old-project\data" --name "Previous invoices"
```

The utility copies the SQLite database and available invoice PDFs into a saved session. It leaves the original files untouched and prints a local history URL. Open that URL to find the imported session. To add the import to an existing collection, also pass `--history-key` with the 32-character key from its bookmarked URL. Keep that key private. Scorecards and batches created in the older temporary Streamlit version are not migrated by this utility.

## Review workflow and controls

Upload a PDF and watch actual processing stages. AI extracts; deterministic code checks values and assigns Ready for approval / Needs review / Blocked. Accepting a ready invoice is a separate human action. Acceptance rechecks balances transactionally and consumes quantity/value once. Accepted invoices remain immutable.

Every check includes a **Next action**, such as selecting a PO, verifying a field or requesting a corrected invoice. Email drafts reflect these actions. Confirming selected values against the PDF clears only their uncertainty flags and records an audit entry; it never bypasses financial rules.

The review queue sorts by explainable priority: Critical for explicitly blocked vendors; High for confirmed/possible duplicates, quantity/value overruns and price variance over 5%; Medium for other review/deferred prerequisites; Low for checks without exceptions. Accepted records sort below pending work. These are workflow priorities, not calibrated fraud probabilities.

## Batch upload

Select one to five PDFs on **New invoice**. Files process sequentially. Each completed/failed result is saved. A provider cooldown stops submission of remaining files, which are marked Not submitted; completed invoices are preserved. The last-batch table and combined follow-up draft for each vendor appear on the queue. No email is sent automatically. Individual failed records support retry after the provider cooldown. A batch does not approve anything automatically.

## Extraction scorecard

Process a realistic fixture first, then open **Extraction scorecard**. Explicitly match an invoice run to its expected fixture and choose **Score original extraction**. The evaluation always uses the saved original extraction, before corrections/verification, and the answer key is never supplied to a provider.

Per-field counts and aggregate accuracy cover invoice/vendor identifiers, amounts, tax rate, date, currency, tax basis and semantic line totals/quantities/prices. Equivalent lines across pages can be aggregated without double-counting. Decimal values compare exactly after Decimal parsing; identifiers ignore case/punctuation. Evidence quality and model confidence are not scored automatically. User-selected synthetic runs are not an independent production benchmark. Score associations are saved in the workspace and exportable as JSON.

## Export

**Export accepted invoices (CSV)** on the queue exports only accepted invoices in the selected session. Includes invoice number, vendor, date, currency, subtotal, tax, total, PO and record ID. Spreadsheet-formula-like text is escaped. This is a clean generic CSV, not certified Tally import compatibility. The JSON record export includes original extraction, decisions, corrections and approvals; source PDFs can be downloaded separately. Exports are not an import/restore system.

## Document readers and policies

Groq: `qwen/qwen3.8-27b`, renders every PDF page to JPEG, up to 3 pages. Gemini optional: native PDF, up to 20 pages. Local reader only parses the labelled basic samples, not varied layouts or scans. Provider availability/quotas require live testing. Groq obeys retry timing with bounded automatic waiting and persisted cooldowns.

Use synthetic documents for demos. Clearly labelled specimen GSTINs and internal references are distinct; no legal registration/validity claim is made. Missing or uncertain fields stay in review. Arithmetic uses Decimal and INR 1 rounding. Unit-price variance <=2% passes; >2–5% review, >5% high-severity review. PO quantities and values have separate cumulative caps. Single company, INR, two-way invoice/PO match; no delivery confirmation, payment execution, tax-law advice or automatic sending.

Real AP controls should check relevant historical obligations across periods. Isolated demo sessions intentionally reset duplicate and PO-balance scope for rehearsals; starting a real AP upload batch must not reset those controls.

## Test pack

See `test_pack/README.md` and `test_pack/answer_key.json`. Run R01 -> approve -> R02 -> R03 together. Test R04–R07 independently as documented. R06 must remain in review because its number/total are absent. Use a new named session to retest without deleting prior evidence. Earlier OCR mistakes and manual corrections must be included honestly in test results.

## Deploy later

The project has not been deployed by this update. Community Cloud entrypoint: `streamlit_app.py`, branch `main`, Python 3.12. Put provider credentials in Advanced settings → Secrets. For durable historical records choose persistent storage hosting instead of assuming Community Cloud has a persistent volume. The retained Dockerfile runs the legacy FastAPI interface; it does not launch the new Streamlit session interface.

## Validation

```sh
python -m pytest -q
```

Tests exercise core invoice checks, corrections, approval, provider error handling, workspace isolation/reopening, original-only evaluation, CSV filtering, batch cooldowns and Streamlit interactions. Mocked provider tests do not establish live extraction accuracy. No production-grade identity, duplicate overrides, approval reversals, credit notes, email ingestion or ERP integration is included in this scope.
