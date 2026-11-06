# UI redesign validation — 6 November 2026

The local redesign uses the existing FastAPI/plain JavaScript application. API paths,
stored identifiers and approval rules remain unchanged. The redesign preserves
the username/password authentication added in the preceding account change.
The existing local deletion of `.env.example` was preserved.

## Executed

- Existing server at http://localhost:8080 returned HTTP 200 for the updated welcome
  page and stylesheet. Starting another copy correctly reported the occupied port.
- `python -m pytest -q`: 38 passed, 1 failed. `test_scan_ocr` requires native
  Tesseract, which is not installed or on PATH. The missing Python `pytesseract`
  dependency was installed before this final run.
- `node --check web/app.js`: passed.
- `node tests/ui-render.cjs`: passed. Covers empty/populated overview rendering,
  invoice dates, escaped folder/file values and individual upload failure reasons.
- `git diff --check`: passed.
- Calculated WCAG contrast for primary/hover buttons, main/secondary text,
  sidebar, disabled controls and all five status pairs: minimum 5.58:1.

## Unverified

Browser access reported “The browser access host is unavailable.” No visual QA
or screenshots were possible. These checks remain pending in an actual browser:

- Welcome and authentication dialogs; username/password account creation/login.
- Demo entry and empty/populated overview appearance.
- Multi-file selection, upload progress and failure dialogs.
- Search, filtering, pagination and CSV/JSON downloads.
- PDF/image preview, field and line edits, confirmation, rerun and approval.
- Vendor/PO forms and folder creation/switching.
- Keyboard/dialog navigation, screen-reader announcements and focus visibility.
- Desktop/mobile layout, table scrolling and absence of page overflow.

The backend suite covers isolation and approval restrictions, but does not replace
these browser checks. The user authorized publication of the UI changes after
the authentication replacement; syntax, renderer, regression and whitespace checks were repeated before publication.
