# Ledger UI handoff

## Design plan and screen structure

UI-only revision of the Streamlit interface. The invoice domain, extraction, store, review service, FastAPI decisions and feature helpers are unchanged. All supplied tokens are centralized in ui/theme.py; native widget colours are aligned in .streamlit/config.toml. IBM Plex font names have system fallbacks; no external font request is required.

| Screen | Top | Main content | Secondary content |
| --- | --- | --- | --- |
| Queue | Attention sentence, small status filters, search | Urgency-sorted selectable table | Exports and last batch follow-ups |
| Detail | Invoice number, vendor, amount | Left: decision, findings, reviewer actions, extracted fields. Right: source PDF | One chronological audit timeline below |
| New invoice | PDF upload | Start review, then actual stage feedback | Reader choice under Advanced |
| Purchase orders | Balance policy | Vendor and PO, numerical accepted/authorised progress | Ordered, accepted and remaining quantities |
| Demo documents | Pack selection | Guided list with expected result, reviewed marker and Run | Existing sample chooser and download retained |
| Scorecard | Original-only evaluation explanation | Fixture association, field counts | Expandable comparison details and export |

Removed the four global metric cards, decorative logo icon, uppercase eyebrow, reader/run strings in the detail header, repeated sidebar paragraphs, raw extraction JSON, raw check codes, database-id fragments and two-step queue dropdown. The three primary navigation items are Review queue, New invoice and Purchase orders. Demo documents, scorecard and confirmed reset sit inside Demo tools. The original sample selector remains for test compatibility and downloading.

## Existing widgets and compatibility inventory

| Purpose | Label / key retained |
| --- | --- |
| Access gate | Demo access code; Open workspace; form access |
| Navigation | nav_Review queue, nav_New invoice, nav_Purchase orders, nav_Demo documents, nav_Extraction scorecard |
| History | Saved review sessions; New session name; Start new session; form create_workspace |
| Reader and fixture | Document reader; Demo invoice; Document set; Run sample review |
| Upload | Upload up to five invoice PDFs; Start review |
| Approval | Approve invoice; approve_{invoice id} |
| PO selection | Purchase order; Select PO & rerun; form po_selection |
| Correction | Scalar labels including Total; field_{invoice id}_{field}; lines_{invoice id}; field_corrections_{invoice id}; Save corrections & rerun |
| Verification | Fields verified against source PDF; I compared… checkbox; Confirm selected fields & rerun; verify_fields_{invoice id}_{review counter} |
| Retry | Retry processing; retry_{invoice id}; Refresh retry availability |
| Source | Download source PDF; pdf_download_{invoice id}; Preview page |
| Scorecard | Extraction run; Expected fixture; Score original extraction; Original extraction field accuracy |
| Exports | Export accepted invoices (CSV); Export review records (JSON); Export scorecard |

Removed widgets: Filter selectbox, Open invoice selectbox, View invoice button and nav_Invoice detail. New widgets: queue_status pills, queue_search text input, queue_table row selection, reset_confirm_{session id} checkbox, Reset demo session and demo_run_{fixture stem}. No existing financial-action label or key changed. tests/test_streamlit.py now asserts the status HTML and queue summary instead of the removed status alerts/metric cards. Added search and confirmed-reset coverage. tests/test_ui.py checks presentation ordering, missing amounts, decimals, escaping and human-readable findings.

## Contrast

See contrast-table.md for calculated WCAG relative-luminance ratios. All specified text pairs pass 4.5:1; control boundaries pass 3:1. The supplied #DDE1E7 divider is only 1.31:1 against white, so it is decorative. Input/select boundaries and the timeline use #7C8795 (3.65:1 against white). Native disabled states and embedded PDF viewer controls require browser inspection; this is not a complete WCAG conformance claim.

Validation result: **63 tests passed**, with one existing Starlette/httpx deprecation warning. Protected backend files were compared with GitHub commit 105ba14cc9af522316529e87b99a6cfb34726b69 and have identical Git blob hashes. No live provider accuracy or browser visual pass is claimed.

## QA checklist

- [x] Compile all changed Python files.
- [x] Existing approval, split-invoice, PO-selection, correction and verification AppTests.
- [x] Session isolation/reopening, scorecard, search and reset confirmation AppTests.
- [x] Deterministic urgency and text escaping checks.
- [x] Original realistic answer-key rule outcomes and scan/page checks remain in the suite.
- [x] Demo order preserved: basic 01 then approve then 02; first copy of 03 then repeat to block, 04 possible duplicate, 05 missing data, 06 PO selection, 07 arithmetic, 08 unknown vendor, 09 scan with AI. Use fresh sessions where independent tests require them.
- [x] Realistic order documented: R01 then approve then R02 and R03; R04/R05/R07 independent, R06 missing values remain null.
- [ ] Live provider extraction not rerun: no API key available here.
- [ ] Keyboard walkthrough not executed in a browser. Expected order: session controls, navigation, filters/search, table selection, review actions, PDF and timeline. Confirm focus visibility, Tab/Shift+Tab, Enter/Space and table keyboard selection locally.
- [ ] 360px browser verification pending. Responsive CSS requests stacked content and 44px buttons; Streamlit supplies responsive columns and scrollable native tables. Check the open sidebar, long filenames, evidence table and PDF independently.
- [ ] 200% browser zoom verification pending. Check queue, detail/actions, PO table and source PDF. No essential text is intentionally hidden at a breakpoint.

A local browser launch was attempted; Chromium installation failed because the downloaded archive was invalid. AppTest is structural/interactivity testing, not screenshot, keyboard or screen-reader verification. No visual-browser pass is claimed.

## Streamlit limits and selectors

No generated class names are used. data-testid hooks for stApp, stSidebar, stMainBlockContainer and stCaptionContainer, data-baseweb select and button kind attributes are framework-owned and can change on upgrades; recheck after upgrades. Native tables remain Streamlit canvas grids: rows carry status text and symbols, not custom coloured HTML pills. Detail banners use consistent status pills. Numeric table columns are right aligned with two decimals but use ungrouped numbers; narrative and PO amounts retain the existing international grouping (₹236,000.00). No Indian-grouping migration was made.

The vendor draft uses Streamlit's native code-block copy control; its tooltip wording is controlled by Streamlit rather than a custom Copy email label. The third-party PDF viewer owns its own controls; a labelled download and raster fallback are retained. IBM Plex is used if installed; otherwise system fonts render. The progress timer updates on service events, not independently every second. No custom JS, paid dependency, build step or new backend endpoint is introduced.

Audit entries use the actor available in existing data: Ledger for automatic events, Demo reviewer for review actions. This does not invent authenticated identities. The historical review counter and full JSON remain in exported records, not in the visible timeline. Reset is destructive only to the selected demo session and requires a checked confirmation; starting a new session remains the preferred way to preserve history.

## Self-critique and corrections

1. Generic dashboard cards: removed in favour of a sentence, filters and a working queue.
2. Repeated rounded cards: reserved panels for PO records and guided demo entries; invoice findings use plain dividers and the decision banner has one accent edge.
3. Technical JSON dumps: replaced extraction with a labelled evidence table and failed checks with expected/found values. Internal identifiers stay out of the review screen.
4. Decorative dashboard wording: removed eyebrow, dotted header strings and logo emoji; kept the ledger text wordmark.
5. Indiscriminate check expansion: only exceptions appear initially, passed checks are collapsed and email text sits with the findings. Native grid/PDF/widget appearance remains recognisably Streamlit.
