# Google Cloud deployment and GitHub updates

This guide deploys two Cloud Run services from one image: a public web app with application login, and a private invoice worker. Firestore stores records; a private Cloud Storage bucket stores original documents; Cloud Tasks dispatches one invoice at a time. Code updates preserve all three.

You need a Google Cloud project with billing enabled and permission to create services, service accounts, IAM bindings, storage, databases, secrets and builds. These steps create billable resources. They have not been executed against your account.

## 1. Create/select your Google Cloud project

1. Select a project with billing enabled. Record its project ID.
2. Ledger accounts run on the backend with username/password authentication.
   No Firebase Authentication provider, browser web app, API key or authorized
   domain configuration is needed.
3. Keep Firestore and Storage browser rules denied. Runtime service identities
   access Firestore and private Cloud Storage using IAM; every application path
   is scoped to the authenticated account ID.
4. Configure billing alerts (alerts do not cap spending).

## 2. Open the code in Cloud Shell

Use the Cloud Shell terminal in Google Cloud Console. Upload/extract this project or clone your GitHub repository. Run all commands from the directory containing `Dockerfile` and `cloudbuild.yaml`.

Set these non-secret values, replacing the examples:

```bash
export LEDGER_PROJECT="your-project-id"
export LEDGER_REGION="asia-south1"
bash scripts/setup-cloud.sh
```

The script asks for the Gemini API key privately and pipes it into Secret Manager. Leave it blank to deploy with independent OCR/rules fallback. It also creates a random signing secret for private demo cookies. Neither secret is written into a tracked file.

The script:

- Enables APIs and provisions the private storage bucket and default Firestore database if absent.
- Creates separate web, worker, task-caller and build service accounts with scoped permissions.
- Creates a queue with at most 3 concurrent tasks and 1 dispatch per second, with retries.
- Builds the image with Tesseract, runs the included regression suite, then deploys.
- Makes only `ledger-web` public. `ledger-worker` accepts the task caller's Google identity; the application additionally verifies its OIDC token and audience.
- Configures both services to use cloud storage and secrets. Cloud Run refuses to start in local-storage mode.
- Prints the public application URL.

A Firestore database location cannot be changed in place. If your project already has a database, the script uses it; make sure its region and data requirements are suitable. The default here is Mumbai, `asia-south1`.

If a step fails, read the actual error and fix the missing permission, billing state, quota or API setting. The script stops at that step. It can be rerun for the same dedicated Ledger resources; do not run it in a production project with unrelated services using these names. It provisions IAM for the named accounts and may redeploy both services.

## 3. Validate accounts and upgrades

1. Open Ledger and test **Create account**, **Log in** and **Log out** using a
   username such as `123` and a matching password of at least 8 characters.
2. Create another account in a separate browser. Confirm folder, invoice,
   original-file and export links from the first account return 404.
3. Try demo while signed out. It has separate invoices and a fictional master.
4. Confirm HTTPS cookies have HttpOnly, SameSite=Lax and Secure attributes.

The setup script enables secure cookies and a 24-hour absolute login expiry.
For an existing deployment, `cloudbuild.yaml` removes the obsolete
`FIREBASE_API_KEY` and `FIREBASE_AUTH_DOMAIN` environment variables on both services.
Remove the old `roles/firebaseauth.viewer` binding from the Ledger web service
identity if it was granted by an earlier setup. Do not remove permissions used by
other applications. The new code does not use Firebase Authentication or its SDK.

Authentication uses Firestore collections `ledger_auth_accounts`,
`ledger_auth_logins` and `ledger_auth_rates`. Runtime identities need existing
`roles/datastore.user`; no additional authentication service is provisioned.
Uniqueness and rate counters use Firestore transactions, so multiple web instances
share the same limits. Login tokens are random; only their hashes are stored.
Expired login records grant no access. They may be removed administratively after
expiry; retained rate records are reused after their window expires. See README
for username normalization, rate thresholds and local SQLite configuration.

Back up Firestore, original files and local databases before upgrading. Existing
invoice paths and legacy account IDs are retained without modification. New
username accounts receive random IDs; registering a matching-looking username
does not claim old Firebase or demo records. A verified administrative migration
would be a separate operation. There is no email/password recovery feature.

## 4. Connect GitHub for automatic updates

1. Push this project to the intended GitHub repository, with these files at its root.
2. In Google Cloud Console → Cloud Build → Repositories, connect your GitHub account/repository. Authorize access to the intended repository.
3. In Cloud Build → Triggers, create a push trigger:
   - Repository: your Ledger repository.
   - Branch regex: `^main$` (or your chosen deployment branch).
   - Configuration: Cloud Build configuration file in the repository.
   - File: `/cloudbuild.yaml`.
   - Service account: `ledger-build@YOUR_PROJECT_ID.iam.gserviceaccount.com`.
   - Substitution: `_REGION=asia-south1` (match the initial deployment).
4. Make a small visible text change, commit it, and push to `main`.
5. Watch the trigger: image build → container tests → image push → private worker deployment → web deployment.
6. Refresh the original Cloud Run web URL after success. The URL and user records remain the same.

A build or test failure stops before deployment. If the worker deployment succeeds but the subsequent web deployment fails, the worker may already be on the new revision; inspect both services. Keep database and payload changes backward-compatible across rolling updates. Future data-model changes may need a migration in addition to pushing code.

## 5. Validate the hosted path before submitting

- Process a normal PDF with Gemini configured. Check the recorded reader says **Gemini**, not fallback.
- Process the scanned sample. Confirm its original is readable and extraction has real evidence.
- Enable the upload's **Use independent OCR and rules** option. Confirm fallback also processes the scan, requires human confirmation, and does not block other invoices.
- Upload 100–120 real sample documents into a **registered account**, not the limited demo. Observe queued/running/completed counts and worker logs. This is the needed hosted load check; local batch tests do not establish your cloud throughput or Gemini quota.
- Close the browser during a queued batch, then reopen the same account. Files and processing history must still be there.
- Approve the 60-chair invoice, then process the 50-chair split invoice in the same session. It should exceed the remaining quantity/value authorisation.
- Redeploy a code change and confirm the previously uploaded invoice, original file, audit history and account access survive.

## Keys, costs and troubleshooting

- **Gemini returns 404:** configure `GEMINI_MODEL` on the worker to a PDF-capable model available to your API project. The default is `gemini-2.5-flash`; availability is not assumed to be permanent. Fallback still works.
- **Gemini key rejected/quota exhausted:** inspect the extraction note. To replace the key, add a new version to `ledger-gemini-key` through Secret Manager; restart/deploy the service to load the new secret at startup. Do not paste it into GitHub.
- **Invoices remain queued:** inspect the Cloud Tasks queue, worker URL, task caller's `run.invoker`, OIDC audience and task service account. A lease prevents double processing. An interrupted task is retried by the queue; after attempts are exhausted use the invoice's Retry action.
- **403 from private worker:** expected for direct browser visits. Only the task identity should invoke it.
- **Firestore permission error:** check both runtime identities have `roles/datastore.user` in the selected project.
- **Account login fails:** check server database permissions, cookie Secure/HTTPS settings, expiry, and durable rate limits. Incorrect credentials always return the same generic error.
- **Scans remain empty:** inspect quality, orientation and OCR page trace. Correct manually if needed. Multi-frame TIFF preview shows the first frame; the downloaded source retains all frames.
- **Public deployment rejected:** your organization may disallow `allUsers` invoker access. Use an allowed project or ask the administrator about the intended public case-study demo.
- **GitHub trigger permission error:** use the provisioned build identity and confirm it can act as both runtime service accounts, write Artifact Registry and deploy Cloud Run.

Limits are intentionally modest: 3 worker instances, concurrency 1 per worker, 3 concurrent queue tasks, up to 250 files per upload selection, and 400 invoices per registered session. This is a small case-study workload; Firestore decisions read the session's invoice history inside a transaction. Large line-item/audit payloads can reach transaction/document size limits before the invoice-count cap. Split workloads into independent sessions where appropriate, and profile before increasing limits. Separate sessions do not share PO consumption.

## Demo retention

Demo access expires after 24 hours. Files/records are not automatically removed merely because a cookie expires. `scripts/cleanup-demos.py` lists expired demo sessions by default and only removes them with `--apply`. Run it using an administrative identity after reviewing its dry-run output; registered account sessions are excluded. If a regular cleanup schedule is desired, configure a restricted scheduled job separately. Uploaded account data otherwise persists until you deliberately remove it through administrative tooling.

This version has no enterprise role model, organization sharing, abuse-resistant public demo admission, password recovery, or automatic demo-to-account migration. For wider public use add admission/rate controls, retention operations and a more granular data access design before raising quotas.

## References

- https://docs.cloud.google.com/run/docs/continuous-deployment
- https://docs.cloud.google.com/build/docs/deploying-builds/deploy-cloud-run
- https://docs.cloud.google.com/run/docs/triggering/using-tasks
- https://docs.cloud.google.com/run/docs/container-contract
- https://argon2-cffi.readthedocs.io/en/stable/api.html
- https://ai.google.dev/gemini-api/docs/document-processing
