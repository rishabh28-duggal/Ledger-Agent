# Goods receipts and bank-detail checks

## Workflow and boundaries

Under Vendors & POs, Goods received accepts independently supplied receipts against stable PO line IDs. Record accepted quantities only. Multiple receipts accumulate; reversals exclude their quantities. Duplicate references, including previously corrected references, cannot be reused. Corrections use revision checks and require reasons; repeated identical requests return the existing record. A correction cannot reduce effective receipts below quantities consumed by approved invoices. Over-receipts trigger review and never enlarge PO authorisation. Units must match exactly; service acceptance, conversions and partial invoice approvals are unsupported.

Change each PO's receipt policy through Change policy with an explicit reason. Old POs default to optional and show Receipt matching not required, rather than a passed delivery check. Changes are retained in the folder control audit. When required, every mapped line is compared against accepted receipts minus approved allocations, aggregating repeated invoice lines. Missing receipts hold the whole invoice. The final approval transaction repeats these checks; competing approvals cannot consume the same received quantities. Existing PO quantity, value, arithmetic and duplicate rules remain independent.

Trusted bank details support one current account per vendor, plus immutable previous versions. Reveal / manage is an explicit authenticated action and is audited. Enter a beneficiary, string account number and IFSC; explicitly confirm independent verification and provide a reason/reference. Saving an unverified account does not establish trust. Invoice extraction and spreadsheet imports never update trusted accounts. Required bank matching is an independent vendor policy with a reasoned audit trail; legacy vendors default to optional. A definite difference from a verified account requires review even when missing bank information is optional.

Gemini and fallback readers have optional bank fields, source evidence and uncertainty. Leading zeros remain intact. Multiple, masked and ambiguous readings require correction; absent fields remain absent. Account spacing/hyphens and IFSC whitespace/case are normalized. Format checks do not prove account existence or ownership. Beneficiary differences are a separate finding; fuzzy name matching is not ownership verification.

Invoice review separates Correct bank extraction from Record external verification. General source confirmation cannot clear bank uncertainty or a business mismatch. External verification requires a method and note/reference using an established vendor contact, never only details printed on the invoice. It binds to the invoice bank fields and trusted baseline version; later changes invalidate it. It does not update vendor trust or approve any invoice. Trusted updates rerun unapproved decisions without changing approved records.

## Privacy, storage and compatibility

No database reset or ownership migration occurs. Existing records use missing-field defaults. Receipt records/history, policy audit and trusted bank versions are additive folder metadata in the existing SQLite/Firestore abstraction. Invoice allocations continue using stable PO line IDs. Approvals also retain receipt policy and bank baseline version/reference at approval time. Procurement edits cannot remove or remap PO line IDs/units with receipt history, or bypass policy-change reasons. Existing whole-master approval locks are retained; independent receipts and reasoned trust/policy operations remain separate.

Normal lists, review responses, JSON audit exports, CSV and Excel reports mask account numbers and bank evidence. General session listings omit sensitive control metadata. Normal JSON backups do not include bank_accounts or full trusted bank history; vendor/PO JSON backups have no accounts. There is no full-bank backup download in this version. Full details are available only through dedicated authenticated reveal/manage actions (including prior versions), and original source files remain independently accessible through existing authenticated document actions. Local SQLite and any infrastructure-level database backups still contain sensitive stored bank information; protect access to them. No account numbers are placed in action URLs or ordinary audit messages/toasts. Policy and receipt audit history is visible in vendor management; bank verification is in invoice audit history.

## Fictional walkthrough

Use fresh, separate folders for the two demonstrations to avoid intentional duplicate detection. In each folder import samples/control-demo/master.json using the existing JSON replacement confirmation. The fixtures are explicitly fictional and do not represent real accounts or payments. PNG invoices can be uploaded normally; their matching text files document the expected extraction. Local image reading needs native Tesseract, or the already configured Gemini reader. Fixture dates are 2026-11-10; update them if rehearsing outside the invoice-date policy window.

Receipt demo:
1. Enable receipt matching for PO-FICTION-100 with a reason (100 fictional chairs authorised).
2. Record receipt GR-FICTION-60 for 60 accepted chairs.
3. Upload receipt-100.png. Compare/correct and confirm extracted source fields. The receipt finding holds the invoice: 100 billed, 60 available, 40 require receipt confirmation.
4. Independently record the remaining 40 under a different receipt reference. Unapproved invoice checks refresh automatically; the receipt finding clears subject to all other rules.
5. Human approval is still a separate action. Attempts to reverse consumed receipts are rejected with an explanation.

Bank demo:
1. Leave receipt matching optional in another fresh folder.
2. Reveal / manage the fictional vendor account: beneficiary Fictional Treasury, account 000000123456, IFSC TEST0000001. Explicitly verify with a fictional rehearsal note/reference.
3. Upload bank-change.png (different fictional account 000000654321). Complete source review. A masked bank mismatch remains Needs review.
4. Correct bank extraction is used only if the source was read incorrectly. General source confirmation cannot resolve the mismatch.
5. Record external verification with a fictional established-contact method and reference. The finding is resolved for this invoice only; vendor baseline and approval remain unchanged. Inspect invoice audit history.
6. To change the trusted account, use its separate vendor action with a reason. Prior versions remain available. Other pending invoices are re-evaluated; past approvals are immutable.

## Verification

Nine focused API tests cover missing/partial/multiple receipts, previous consumption, repeated mapped lines, units, over-receipts, duplicate/retried receipts, concurrent approvals, correction restrictions, reasoned policy changes, access isolation, bank normalization/leading zeros, mismatches/IFSC/name differences, uncertainty/correction, required/no verified baseline, separate external verification, baseline-version invalidation, masking and reports, untrusted imports, immutable approvals and legacy optional behavior. Existing regressions and frontend render checks are also run. Live Firestore, Cloud Run and paid Gemini integration are not claimed as verified. See the implementation response for browser checks actually completed.

Local verification result: complete regression suite 66 passed, with the existing test_scan_ocr failure due to missing native Tesseract. Focused controls tests (9), JavaScript syntax/render checks, Python compilation and whitespace checks pass. HTTP smoke checks served the preview and new browser code on port 8086. Native browser opened the dark landing, then capture failed twice with "window crop is outside captured monitor". Workflow screenshots, light/dark workflow rendering and mobile visual checks remain unverified; API tests are not browser verification. No live cloud or Gemini call was performed.
