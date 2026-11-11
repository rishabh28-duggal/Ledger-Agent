# Final UI polish

Implemented against the existing application, without a walkthrough or new business rules.

- Shared Cobalt + Tangerine light tokens and separated, medium-navy dark surfaces. Existing theme preference is applied before the stylesheet paints where browser storage is available.
- Stronger type, consistent panel/control/dialog radii, compact account forms, bright square summary cards and quieter semantic badges. Summary selection, counts, grouping, filters and export scope are preserved.
- Desktop invoice review uses the viewport with a selected-page Fit page preview, deliberate zoom/pan, fixed tabs and visible decision area. Smaller/shorter windows retain page flow. Existing viewer rendering and authenticated preview endpoints are unchanged.
- Finding groups initially display three checks, with remaining checks disclosed; raw findings and evidence are retained. Source confirmation uses its existing aligned grid and backend policy.
- Clean Save is disabled; confirmation-only changes have their own label and can be undone. Field edits invalidate source confirmation. Save clears local dirty flags only after success. Approval has an explicit pending state and ignores repeated submissions.
- Dashboard return restores its scroll independently of the queue. Existing filter and queue state persist.

## Files

`web/style.css`, `web/index.html`, `web/theme-init.js`, `web/app.js`, `tests/ui-render.cjs`, `tests/review-ui.cjs`, and the invoice-review documentation. Authentication, storage, extraction, deterministic policy and deployment configuration are unchanged.

## Verification on 2026-11-11

- `python -m pytest -q`: 70 passed, one existing `tests/test_cloud.py::test_scan_ocr` failure because native Tesseract is missing on this Windows host.
- `node --check web/app.js` and `node --check web/theme-init.js` passed.
- `node tests/ui-render.cjs` passed, including numerical 4.5:1 contrast checks for theme/action/semantic/summary token pairs and existing filter, grouping, bulk-approval and sidebar coverage.
- `node tests/review-ui.cjs` passed, including clean and confirmation-only Save, undoing confirmation, duplicate pending approval prevention, clearing dirty flags after saving, approval guards and independent dashboard/queue return scroll.
- A live, isolated local server with normal private-demo authentication processed `01_happy_60_chairs.pdf`, rendered its preview, saved explicit source confirmation and accepted a separate human approval request. `02_split_50_chairs.pdf` then remained Needs review and approval returned 409 for PO overrun. This used genuine embedded-PDF fallback, not Gemini or injected extraction answers.
- `git diff --check` passed.

## Visual limits

Native browser inspection covered the minimalist landing at narrow and full laptop window widths and the dark account dialog, including visible keyboard focus. Browser window control became unreliable after user input changed the active window. Populated dashboard/review, the final account-spacing adjustment, light-theme visual rendering, exact 1440/1280/768/390 viewport checks, browser console/network inspection and the full browser approval journey remain unverified. API/state tests do not substitute for these visual checks. No live Gemini, Cloud Run or Firestore verification was performed.

The account dialog spacing was reduced after the observed scrollbar. The user explicitly requested committing and pushing this pass; secrets, local invoice databases and unrelated editor/design files are excluded.
