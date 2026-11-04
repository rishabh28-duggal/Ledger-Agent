# Realistic invoice test pack

Seven synthetic invoices, eight pages, three visual vendor styles. These are evaluation fixtures, not real vendor documents. They use the existing `samples/master.json` vendors/POs and fictional registration identifiers. No purchasing-master changes are needed.

## How to test

Use **Groq vision** or **Gemini**, not the local labelled-text reader. Upload PDFs only. Never include `answer_key.json` in an extraction prompt: that would give the model the answers.

Compare the result against `answer_key.json`: vendor, invoice number, invoice date, PO reference, currency, line quantities/prices/amounts, subtotal, tax and total. Check source evidence too. Missing information must remain null. A correct final status alone does not prove extraction accuracy.

| PDF | What it tests | Expected result / setup |
| --- | --- | --- |
| R01 | Modern Acme table layout; 60 chairs | Fresh workspace: Ready for approval. Explicitly approve it. |
| R02 | Second partial invoice; 50 chairs | After R01 is Accepted: Needs review; only 40 chairs / INR 94,400 remain. |
| R03 | Different layout and vendor-name abbreviation, same invoice identity | After R01 has been processed: Blocked duplicate, even though the file hash differs. |
| R04 | Two-page Orbit invoice with page subtotal and brought-forward amount | Independent run: 200 stands, INR 200,000 net + 36,000 tax = 236,000. No double-counting page carry-forward. |
| R05 | Nova invoice with no PO reference | Independent run: Needs review, two candidate POs. After selecting the intended eligible PO: Ready for approval. |
| R06 | Invoice number and payable amount not supplied | Needs review. Keep invoice_no and total null; do not invent an invoice number or compute a supposedly extracted total. |
| R07 | Slightly rotated scanned Acme invoice, no text layer | Independent fresh run: 10 chairs; INR 23,600 total. Ready only if extraction and evidence are reliable; otherwise review is appropriate. |

## Run order matters

Run R01 -> approve -> R02 -> R03 together. Reset before R04/R05/R07 when testing them independently. R06 and R07 have similar quantities and amounts; processing them together can legitimately trigger a possible-duplicate finding. Re-uploading the same file also triggers a duplicate; review the original record or reset the demo when repeating an extraction test.

All fixtures are dated **4 November 2026**. Tests before that date will trigger the future-date policy; testing more than 365 days later will trigger the old-invoice policy. To change dates, update/re-run `scripts/make_realistic_pack.py` and regenerate the answer key together.

## Important evaluation boundaries

These invoices are more varied than the original labelled samples, but remain controlled synthetic fixtures. They do not represent every real-world format or establish production accuracy. A live extraction run is still required. The generator checks arithmetic, the scan's missing text layer and page counts. Rule tests validate expected decisions from the answer-key inputs; they do not validate OCR/LLM extraction.

Evidence page/snippet and confidence depend on the extraction result, so they are not pre-filled in the answer key. The two-page invoice may be extracted as two lines (80 and 120) or one correctly aggregated 200-unit line; both represent the same purchase. The model must not treat the brought-forward net value as a third item.

Confidence remains self-reported. A review outcome due to genuine uncertainty is safer than an unsupported Ready result. Record both extraction errors and conservative review outcomes separately during evaluation.

## Updated identifier fixtures

New PDFs use clearly labelled, 15-character GSTIN-format test values and separate internal vendor references. Acme: `36ZZZCA0001A1Z8`; Orbit: `36ZZZCO0002B1Z8`; Nova: `36ZZZCN0003C1Z8`. These are syntactic specimens only: no checksum, issuance, registration or legal-validity claim is made. Internal references remain `DEMO-ACME-001`, `DEMO-ORBIT-002`, `DEMO-NOVA-003` in their own field. Do not use them for real transactions.

Use the updated PDFs together with the updated master. In an existing demo workspace, choose **Show demo reset → Reset my workspace** to clear test history and reload the latest master. Do not combine old PDFs with new master identifiers. The changes improve clarity but do not establish that live model extraction is error-free.
