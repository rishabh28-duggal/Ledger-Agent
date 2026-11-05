# Independent invoice reader

The fallback uses no Groq key, no Gemini key, no other hosted AI service, and no answer-key lookup. Tesseract is installed inside the deployment image. Text and OCR reading always happen outside the approval transaction.

## When it starts

- Missing Gemini key, rejected credentials, unsupported/unavailable model, quota failure, timeout, invalid schema, or incomplete model response.
- A transient HTTP 429/5xx gets one short retry. Permanent errors fall back immediately. Network failures get one retry.
- A per-instance 60-second circuit breaker prevents a broken provider from consuming a fresh timeout for every invoice. Other instances may still try Gemini.
- Users can explicitly choose independent OCR/rules when uploading, to demonstrate fallback without disabling the server key.

## Reading the document

1. Validate the input bytes, size (10 MB) and page count (30).
2. Reject encrypted, invalid or oversized files with a per-file explanation; continue uploading other files.
3. Extract embedded text separately from every PDF page.
4. Pages with fewer than 60 characters use local Tesseract OCR at a readable rendering scale. Images use OCR on each frame; orientation metadata is respected.
5. Preserve page number, reading method and character counts. Image and PDF originals stay available for comparison.

## Field rules

| Field | Accepted evidence | If uncertain or missing |
| --- | --- | --- |
| Vendor | Explicit Vendor/Supplier/Seller/From label; conservative standalone company heading | Empty if no plausible heading; human must confirm |
| GSTIN | Explicit GSTIN label and 15 alphanumeric characters | No legal validation, master substitution or OCR-character repair |
| Invoice number | Invoice/Invoice no./Invoice number/# label and a reference containing a digit | Empty; never use a PO number as an invoice number |
| Date | Date/Issued/Invoice date label; otherwise an explicit day-month-name-year date | Parse supported formats only; numeric day/month ambiguity needs source confirmation |
| PO reference | Purchase order or PO label, followed by a PO-prefixed reference | Empty; policy engine handles candidate matching |
| Currency | A printed INR/USD/EUR/GBP/AED code | Empty; never infer INR from geography or master data |
| Subtotal | Entire line labelled Subtotal, Sub total, Taxable value or Net subtotal | Ignore page-specific totals and carried-forward amounts |
| Tax | Explicit Tax/GST/Total tax line and amount | No assumed zero tax or calculation from the PO |
| Tax rate | Tax rate label or GST followed by a printed percentage | Percentage points; no assumed 18% |
| Tax basis | Explicit exclusive/inclusive label or prices include/exclude GST/tax wording | Empty; never infer from the price alone |
| Invoice total | Entire line labelled Grand total, Total, Amount payable or Balance due | Never choose the largest amount or add up line items to invent a missing total |
| Lines | Explicit pipe-labelled items, or description + quantity + unit + price + amount row | Keep partial/missing data visible; no inferred descriptions, quantities or prices |

Different values for the same field make it null with a conflict marker. Formatting differences may conservatively require correction. Multi-page line items remain separate and are summed by the policy checks. A repeated printed item is not silently deduplicated because it may represent a real second shipment.

Every fallback value, including the complete line-item table, starts unconfirmed. The reviewer compares the source, corrects values, explicitly confirms the displayed information and saves. Confirmation clears extraction uncertainty only; it does not bypass any business rule.

## If OCR also fails

Create a saved invoice with empty fields and a Manual review explanation. The original remains downloadable. The user can type fields and items, select the PO, confirm the original, and rerun deterministic checks. The rest of the queue continues.

## Known boundaries

OCR quality varies with scan clarity, language, layout, skew, handwriting, and table structure. English printed invoices are the tested path. Matching one invoice to multiple POs and currency conversion are outside this version. OCR, self-reported AI confidence and correct arithmetic do not establish a supplier's legal identity or entitlement to payment.
