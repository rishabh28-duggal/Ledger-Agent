# Review references and natural document layout

This change stays local for review. Nothing has been committed or pushed.

## Review workspace

The desktop split is approximately 50/50. The source opens at Fit width and uses natural height; the browser scrolls through the source, selected review tab and compact decision area. A slim sticky header keeps Review queue, invoice identity and truthful status reachable. Tablet/mobile stacks the panels. The main source and review panels have no fixed viewport height or independent vertical content scroller. Wide tables and deliberate document zoom may scroll horizontally; the expanded document viewer intentionally permits panning.

PDF previews use the existing PDFium renderer and authenticated selected-page endpoint. Requests account for displayed width, zoom and device pixel ratio, with width capped at 3200px, height at 8192px and PDF bitmap area at 12 million pixels. Original bytes are unchanged. Single-page previews hide redundant previous/next controls. Expand opens the current page with its own controls and source state; closing restores focus and outer page position. Tabs, field edits and normal polling do not rebuild the viewer.

## Vendor and PO resolution

The early Vendor & purchase order section reports matching against the saved invoice. It explicitly distinguishes unsaved invoice edits from saved matching results.

- Add & approve vendor opens the existing vendor form in a review dialog. Extracted name, GSTIN and supported reference are suggestions. Fields can be corrected. An explicit independent-verification/authority checkbox and reason are required by the server. Bank data is not copied into trusted bank records or marked verified.
- Existing vendors are selectable in the same dialog. The server rejects creation when GSTIN matches or normalized names/aliases are sufficiently similar. Linking a verified existing identity can add the observed invoice name as a recognised alias. A conflicting GSTIN still raises the existing check. Blocked vendors cannot be approved through this action.
- Select existing PO lists open POs for the saved matched vendor. Selection persists through the existing `selected_po` mechanism and reruns the ordinary decision engine.
- Add authorised PO reuses the current PO fields and model validation. Only the extracted PO reference is suggested. Budget, quantities, prices and line items start empty and must come from independent purchasing authorisation. The server requires explicit authority confirmation and a reference/reason. Duplicate normalized PO references are rejected and can be linked instead.

The new endpoint is `POST /api/sessions/{sid}/invoices/{iid}/procurement`. It uses normal authentication, folder ownership, CSRF protection, expected-run checks, existing editable-invoice checks and the same master validation/application functions as Vendors & POs. Existing master locks after invoice approval remain in force. A locked folder cannot add or alter vendors/POs through this shortcut; a matched invoice can still select an existing open PO. There is no new procurement permission tier or bypass.

Reference changes and invoice check results are saved atomically. The invoice revision advances; vendor approval, PO creation/linking, actor, authorisation reason, reference values and resulting check codes/levels are recorded in invoice and folder control audit history. These operations do not approve the invoice. Source uncertainty, duplicates, arithmetic, remaining balances, receipts and bank verification remain active.

## Draft preservation

A successful resolution updates saved references, findings, bank review controls and matching status in place. It does not replace the invoice form or source viewer. Unsaved invoice fields and confirmation state stay intact. A user-edited PO choice is retained; a previously untouched PO selection follows the newly persisted link. The next explicit Save evaluates the draft against the latest revision. Failed requests leave the dialog and draft available. Cancel/close before submission creates no record. Closing a dialog after a submitted request cannot undo a completed server transaction.

## Checks

- Five API tests in `tests/test_review_procurement.py`: missing vendor and PO creation, required authority, duplicate identity/reference detection, linking, real rechecks, unchanged extraction/uncertainty, other findings preventing approval, stale revisions, audit, ownership, CSRF and master locks.
- Stateful `tests/review-ui.cjs` now also checks dialog cancellation without requests and successful in-place reference updates retaining fields, active tab and viewer state.
- Existing PDF/image preview tests and frontend rendering/filter/approval checks pass.
- Full regression: 75 passed, one existing `test_scan_ocr` failure because native Tesseract is unavailable on this Windows host.
- A real local HTTP run processed `samples/08_unknown_vendor.pdf` through the existing embedded-text fallback, added a verified fictional vendor and independently entered PO, linked and rechecked without replacing extracted data, and confirmed invoice approval still required source confirmation.
- Live Gemini, Firestore and Cloud Run are not verified by these local checks. Browser checks and any remaining visual limitations are reported in the response; code/API tests do not establish visual correctness.

## Visual verification

Inspected the actual local application in Brave at the available desktop window size, using isolated fictional records: light and dark review surfaces, a multipage PDF, page 2 and expanded preview, Escape/focus return, full-width scanned image, whole-page scrolling, missing-extraction findings, vendor verification dialog and authorised-PO dialog. The PO budget/quantity/price fields were empty. Single-page controls omitted Previous/Next. Exact 1280?720, 1440?900 and mobile viewport checks were not performed; those responsive layouts remain a manual verification item. Browser fixtures were isolated and did not modify existing user invoices.
