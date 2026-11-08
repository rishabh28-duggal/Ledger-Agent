# Slate + Apricot UI update

The landing page now contains one headline, a short description, demo entry and account actions. The private demo opens Upload invoices; its optional example PDF is selected only on request and is not automatically processed. Existing account isolation and approval rules remain unchanged.

The overview uses neutral surfaces, lighter slate dark mode, compact folder/search/date controls, an additional Filters drawer, counted status navigation and grouping beside the results heading. Vendor, inclusive invoice dates, currency-specific amount ranges and PO filters combine without changing approval eligibility. Draft filters apply only on submission; Cancel/Escape discards edits. Search is debounced without rebuilding its input. Filter changes reset pagination and clear selection. Summary counts ignore only the selected status. The table precedes amount charts. Dashboard corner radii use shared tokens.

Export Excel retains the current preview behavior: overview exports the complete selected folder scope without overview filters; queue exports retain their existing status/search scope. The button has an accessible description explaining that filtered-out invoices are included in the folder export. No backend export code changed.

## Checks and limits

- JavaScript syntax and UI renderer tests pass, including contrast token pairs, combined filters, month boundaries, invalid ranges, counts, pagination/selection reset, filter draft Apply/Cancel, demo loading/retry and existing bulk-approval checks.
- Full Python regression suite: 46 passed; test_scan_ocr fails because native Tesseract is absent on this host. Docker already installs Tesseract.
- Native browser screenshots inspected: landing, private demo entry/upload, empty overview at approximately 850px and 1536px, and the Filters drawer. Browser input conflicts prevented complete visual QA.
- Dark mode, populated folders, long names/large counts, exact 1440/1024/768/390px widths, text zoom and complete keyboard flows remain visually unverified. Renderer checks are not browser verification.
- No live cloud, Gemini, ownership, invoice data or deployment configuration changes.
