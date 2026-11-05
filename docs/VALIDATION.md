# Validation record

## Executed locally

**23 tests passed** in the final regression run.

The included suite exercises the real FastAPI API, SQLite transactions, embedded PDF extraction and installed Tesseract OCR. It does not require paid API credentials.

- Authentication required for sessions; signed demos remain private to their owner.
- Cross-account session, file, invoice and export access is denied.
- Cross-origin write requests and malformed IDs are rejected.
- Varied-layout PDF and two-page invoice totals are read without using page subtotals as the final total.
- The supplied scanned PDF is processed using local OCR.
- Missing fields stay null; conflicting totals become explicit unresolved values.
- A malformed invoice does not cancel a later valid upload.
- Source confirmation does not bypass arithmetic or policy findings.
- Concurrent approval requests cannot overconsume the same PO balance.
- Duplicate blocking is scoped to the current review session.
- Stale edits are rejected and source evidence cannot be forged by the client.
- Approved invoices remain immutable with audit events; their master is locked.
- CSV formula prefixes are escaped.
- Public requests cannot call the internal worker endpoint.
- Registered account sessions start with an empty procurement master.
- A 120-document local batch completes with three concurrent readers. The documents deliberately share identical contents, so 119 are duplicates; this checks completion, concurrency and duplicate refresh, not 120 diverse-layout extraction accuracy.

Syntax checks also cover Python compilation, browser JavaScript parsing and deployment shell syntax.

## Not executed here

- A real Gemini call: no Gemini key was supplied for this build. Response handling is covered with simulated provider responses in the suite.
- Live Google Cloud Run, Cloud Tasks, Firestore, Storage and IAM integration.
- Real Firebase signup, login, password reset and revoked-token behaviour.
- Hosted 100+ document throughput or Gemini quota capacity.
- Visual rendering, actual keyboard/screen-reader operation, mobile browser behaviour, and Firebase CDN loading: the remote browser could not reach the local preview server. Styles, labels and interactions were implemented and statically inspected; complete the browser checks below before submission.
- Building the Docker image or running `gcloud`: those environments/credentials were not available here.

## Browser acceptance checklist

1. Desktop and mobile: landing headings/actions, sidebar, session selector and tables remain readable without page-level horizontal overflow.
2. Keyboard: reach all buttons, navigate dialogs, see focus rings, close dialogs with Escape, and tab to labelled fields.
3. Demo: choose Try demo, upload a clean PDF and a scan, inspect the originals, edit a line item, confirm the source, rerun and approve.
4. Multi-file upload: navigate to the queue during upload and ensure counts continue updating. Failed uploads display their own explanations.
5. Review: no user edit is overwritten by a background refresh while focus remains inside the field form.
6. Source: verify PDF page navigation, scan image preview and original download on the browsers used for the interview.
7. Accounts: create, sign out, sign back in, reset password and test isolation with two separate browsers.
8. Deploy: push a visible change to GitHub, wait for successful Cloud Build, and confirm the same URL and saved invoices.
