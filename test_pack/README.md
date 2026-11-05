# Additional invoice fixtures

These PDFs use different layouts and include a real image-only scan. They are fictional evaluation documents, not payable invoices. `answer_key.json` is for human comparison only; production extraction code never reads it.

| File | Scenario |
| --- | --- |
| R01 | Modern single-page happy path |
| R02 | Partial invoice that can overrun the remaining PO after R01 is approved |
| R03 | Reissued/duplicate identity |
| R04 | Two-page invoice; final summary must include both shipments |
| R05 | Missing PO / ambiguous matching |
| R06 | Incomplete critical information |
| R07 | Scanned image-only invoice |

Use a demo session with the supplied fictional master, or load the sample master into an account session. New sessions have independent duplicate and consumption histories. Missing fields must remain missing even if an expected answer seems obvious.

The simpler `samples/` pack is available from the app's Upload screen. See `docs/DEMO.md` for a five-minute rehearsal.
