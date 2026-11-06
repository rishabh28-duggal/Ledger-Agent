# Workspace update — 6 November 2026

Implemented from the user's written request, screenshots and supplied recording.
The recording was inspected as a visual reference; it is not included in Git.

## Updated workflow

- Upload page: sample-invoice section removed. Choose files/folder, then **Run
  invoice checks**. Saved uploads still open the review queue.
- Review queue: bordered **Review invoice** buttons, invoice selection, vendor
  grouping, **Select all ready**, **Approve selected** and **Approve all ready**
  below the table. Selection spans matching results across pagination, within the
  current folder. A confirmation names the number of invoices being approved.
- Bulk approval calls the existing approval endpoint sequentially with each
  invoice's expected run. Every invoice is checked again against current vendor,
  source, duplicate and PO constraints. One failure does not cancel the others;
  failed invoice names and reasons are shown. This is invoice approval, not payment.
- Detail: findings moved above extracted fields, unresolved findings have larger
  highlighted text and next steps, a jump-to-findings control, and larger approval
  buttons. Source confirmation and save/rerun remain separate actions.
- Overview: distinct total, review, ready, approved and blocked blocks. All-folder
  history is the default; folder/date/outcome/search filters drive the counts,
  graph, amounts and table. Group by date, month, year, vendor, invoice number, PO,
  outcome or folder, or disable grouping. Open links retain the invoice's folder.
- Amounts: total known invoice value, approved value and unapproved value, plus
  monthly bars and an exact-amount table. Different currencies are never summed;
  a currency selector controls the amount display. No invented progress or metrics.
- **Download as Excel** generates a real `.xlsx` workbook, respecting the current
  view's folder, date, outcome, search and grouping. Amount cells are numeric;
  supplied strings are stored as literal text to prevent formula execution. CSV
  and JSON API exports remain available for existing integrations.
- Light/dark themes and the desktop sidebar preference are saved in this browser.
  Mobile navigation stays collapsible. Hidden navigation is removed from keyboard
  focus. Page and section headings are larger; wide tables scroll in their panels.

## Verification

- `node --check web/app.js`: passed.
- `node tests/ui-render.cjs`: passed. Covers renderers, filters, grouping, monetary
  currency separation, partial bulk-approval failures, theme and sidebar behavior.
- `python -m pytest tests/test_workspace.py -q`: 4 passed. Covers all-folder
  ownership, Excel output/filtering/formula safety and PO balance rechecking.
- `python -m pytest -q`: 42 passed, 1 failed. The existing `test_scan_ocr` failure
  requires native Tesseract, which is absent on this Windows host. The deployment
  Dockerfile already installs it; the OCR code was not changed.
- Python compilation and `git diff --check`: passed.
- Live Uvicorn/HTTP smoke test with disposable demo data: upload, all-folder
  listing, actual Excel workbook download and updated HTML passed.
- Browser access returned “The browser access host is unavailable.” Rendered
  desktop/mobile appearance, real pointer/keyboard interaction and screenshots
  remain unverified. Renderer tests are not claimed as visual verification.
- Live Cloud Run/Firestore integration was not exercised here.

No secrets, local databases, recording or extracted video frames are committed.
The pre-existing local deletion of `.env.example` is excluded.


## Queue consistency and procurement follow-up

- Search, Status and Group by now have uniform visible labels and 44px controls,
  aligned with Refresh. Bulk actions have equal heights, with blue for selected
  approval and green for approving all ready invoices. Disabled actions retain
  readable tinted states. Review buttons are blue.
- All rows can be selected, including blocked/review invoices. Select all covers
  every matching page. The summary distinguishes selected invoices from those
  eligible for approval; non-ready invoices cannot bypass checks. Selecting all
  updates the controls without replacing the focused checkbox.
- New folders contain independent copies of the repository vendor/PO records,
  displayed as ordinary procurement data. Existing untouched empty lists are
  initialized on access, with existing completed invoices rechecked and audited.
  Custom lists, folders with approvals and deliberately cleared lists stay intact.
  Invoice data, files, duplicate history and account IDs are not reassigned.
- The former sample-master loading control is removed from the interface.
- Verification: 46 backend tests passed. The one remaining OCR test requires the
  missing native Tesseract program. JavaScript checks cover selecting blocked rows,
  select-all across pages, eligibility counts, filters and existing UI behaviors.
  New procurement tests cover initialization, independent folders, revalidation,
  idempotence and preservation of custom/approved/intentionally empty data.
- Browser access remained unavailable, so visual layout verification is pending.
