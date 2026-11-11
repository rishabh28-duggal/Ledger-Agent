# Removing folders and invoice files

Before upload, use **Remove** beside a selected file. This changes only the local selection and is disabled while a batch is uploading.

After upload, open the invoice and choose **Delete file** beside the source controls. Confirm the named file to remove it from the folder. Cancel preserves the record and unsaved edits. Approved invoices cannot be deleted individually because their approval and PO consumption must remain intact.

Use **Delete folder** beneath the current-folder selector to remove a folder and all its invoice history from the workspace. The confirmation names the folder and gives its current invoice count. Deleting the last folder creates a new empty folder. Unsaved invoice edits are discarded only after successful deletion.

These are audited soft deletions: saved records, approval history and original source bytes remain in storage for audit purposes. They are excluded from normal reads, downloads, searches, exports, matching, quotas and folder lists. There is no restore or permanent-purge control in this update.

Both SQLite and Firestore filter tombstones at the repository boundary. Writes to a deleted folder are rejected. Invoice deletion advances its run, invalidates a worker lease and reruns checks for remaining unapproved invoices. Workers cannot resurrect a removed invoice; missing/deleted Cloud Tasks targets acknowledge without retry. Approved records remain unchanged. Every endpoint uses the normal owner namespace and CSRF middleware. Expected invoice runs and folder versions reject stale confirmations.

Verification: four deletion API tests cover stale revisions, approval protection, duplicate rechecks, hidden original/preview/download access, folder lists and overview exclusion, cross-account denial, CSRF, audit retention and a worker finishing after deletion. Frontend tests cover pre-upload removal, upload-in-progress guards and cancelling a saved-file deletion without writes or lost edits. Existing frontend checks pass. Full Python suite: 79 passed; one pre-existing OCR test fails because native Tesseract is unavailable on this host. Live Firestore and Cloud Storage were not tested.

Browser spot-check in the isolated local Chrome preview: the Delete file button opened a readable named-file confirmation, and Cancel returned to the unchanged invoice and source viewer. Real deletion and isolation were verified by API tests; no live-cloud deletion was performed.
