# Vendor spreadsheet import

On Vendors & POs, choose **Import vendor Excel**. Select an XLSX or UTF-8 CSV file (up to 2 MB, 500 data rows and 20 columns), then explicitly choose **Preview file**. File selection alone does not upload or save records. The dialog prominently names the current folder.

Use Vendor name (required), GSTIN (optional), Status (Active or Blocked, blank defaults to Active), and Aliases (semicolon-separated). Headers ignore case and separators, including vendor_name. Download the template from **Backup & template** and remove its clearly fictional example row. Its GSTIN is intentionally blank. A Vendors worksheet is preferred; other workbooks with multiple nonempty sheets require a selection. Legacy XLS, macros and formula fields are unsupported. GSTIN checks validate format only, not registration or legitimacy. Spreadsheets are never sent to Gemini.

Preview lists New, Existing, Conflicts and Invalid counts and row-level validation. Existing matches default to Skip; opt into Update matched vendors and preview again to see proposed changes. Matching uses normalized GSTIN and the existing exact name/alias rules, without fuzzy merging. Duplicate/conflicting identities are skipped. Updates preserve IDs, PO references, nonblank stored GSTINs and blocked status, and merge aliases while retaining recognized old names. A folder with approvals remains locked to all procurement imports under the existing policy.

**Import N vendors** saves only eligible rows. Invalid/conflicting and skipped existing rows are explicitly listed. Final counts and row details remain available for correction. Any transactional failure rolls back the whole import. A connection error may leave the outcome unknown: retry the same confirmation safely. Signed previews expire after 15 minutes, bind account and folder, and are revalidated against the latest master and approval lock. Atomic receipts prevent repeated or concurrent confirmations from importing twice. SQLite and Firestore use the existing storage abstraction. Imports audit procurement changes and rerun checks on completed, unapproved invoices; approved invoices remain untouched.

**Download vendors & POs** is a JSON backup, separate from invoice reports. **Import vendors & POs** retains its existing whole-master replacement behavior, now with explicit confirmation explaining replacement rather than merge. Invoice Export Excel scope is unchanged; its accessible description distinguishes all-folder overview, selected-folder overview and queue-filtered reports.

## Validation

- 11 focused import tests cover CSV/XLSX, BOM/header variants, statuses, GSTINs, duplicates/conflicts, skips/updates, blocked/locked protection, formulas/malformed files, worksheet selection, cross-account/folder isolation, stale/expired previews, concurrent/repeated confirmation, preview without writes, rollback, PO preservation and invoice rechecking.
- JavaScript syntax and renderer tests pass, including import controls, preview escaping and existing dashboard/bulk behavior.
- Native browser inspection covered the dark-theme Vendors & POs page and import dialog. Computer Use was stopped before file selection finished. Complete browser import, light/mobile layouts and live Firestore remain unverified.
- The native OCR regression requires Tesseract, absent on this host; the deployment image already installs it.

The original dashboard summary appearance is retained. Only the theme-toggle button keeps its requested 6px corners. No secrets, local invoice databases or deployment settings are part of this change.
