# A five-minute demonstration

Use a clean private demo for the interview. Rehearse these steps using the deployed URL; do not rely on an untested Gemini key.

## 0:00 — Show the problem and workspace

“AP teams receive differently formatted PDFs and scans. Ledger reads them, checks procurement rules, and makes exceptions clear. A person approves separately.”

Choose **Try the demo**. Point out the private workspace, preloaded fictional vendors/POs, and the three entry options on the welcome screen. Show that the interface explains checks in business terms.

## 0:40 — Happy path

1. Upload invoices → try **A clean invoice**.
2. Follow the invoice through the review queue to its source preview and processing trail.
3. Show the printed fields and PO-1042 match. If fallback was used, explain it and compare/confirm all present values before saving.
4. Click **Save & rerun checks**, resolve any actual reading errors, then **Approve invoice** when ready.
5. Show PO-1042's remaining quantity/value in Vendors & POs. Approval records a decision; it never moves money.

## 1:50 — A scanned invoice / API failure

1. Start another session if you want an independent PO balance.
2. Upload invoices → select **Use independent OCR and rules** → try **A scanned invoice**.
3. Open the invoice, show “Local OCR + rules,” page reading details, and the original image.
4. Demonstrate that the rest of the queue continues even if extraction needs correction. Confirm the source and rerun checks.

## 2:50 — Two meaningful exceptions

- **Missing information:** try the corresponding sample. Highlight null fields and specific next steps. Do not fill absent information from the master or invented values.
- **Arithmetic error:** try that sample. Human confirmation of extraction cannot make incorrect printed arithmetic pass. Show the vendor follow-up draft; Ledger does not send it automatically.

For a procurement-consumption alternative, upload `samples/02_split_50_chairs.pdf` after approving the 60-chair invoice in the same session. The remaining PO has only 40 chairs, so the second invoice needs review.

## 4:00 — History and auditability

Show the invoice audit trail, original extraction, CSV export, and source download. Start a new session, then switch back to the old session to show preservation. Explain that separate sessions have independent duplicate/PO histories.

## 4:40 — Design judgment

“Gemini reads the document; the policy engine makes reproducible checks; the reviewer makes the approval. If the provider fails, local OCR and explicit rules keep files moving into review without inventing data.”

For the follow-up discussion, show the 120-document local test result and state its limits: real hosted throughput still depends on quotas, worker resources and document complexity.
