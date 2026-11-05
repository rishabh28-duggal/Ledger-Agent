# Google Cloud deployment and GitHub updates

This guide deploys two Cloud Run services from one image: a public web app with application login, and a private invoice worker. Firestore stores records; a private Cloud Storage bucket stores original documents; Cloud Tasks dispatches one invoice at a time. Code updates preserve all three.

You need a Google Cloud project with billing enabled and permission to create services, service accounts, IAM bindings, storage, databases, secrets and builds. These steps create billable resources. They have not been executed against your account.

## 1. Create/select your project and configure Firebase

1. Open Google Cloud Console, create/select a project, and enable billing. Record its **project ID**, not its display name or project number.
2. Open Firebase Console and add Firebase to that **same existing Google Cloud project**.
3. In Firebase Authentication, enable **Email/Password** sign-in. Email verification is not enforced by this case-study version; do not represent it as a verified enterprise identity system.
4. Add a Web app in Firebase Project settings → Your apps. Copy `apiKey` and `authDomain` from the web configuration. These are public project configuration, not a service-account secret. Never put an Admin SDK private key into the browser.
5. Keep the Firestore and Storage browser rules denied. This app accesses data through the backend, using its Google service identity. The included `firestore.rules` and `storage.rules` are deny-all for browser clients; publish them through the corresponding Firebase rules editor (or Firebase CLI with `firebase deploy --only firestore:rules --project YOUR_PROJECT_ID`). The Cloud Storage bucket provisioned below uses IAM and public access prevention independently.
6. In Google Cloud Billing, configure a budget notification. A budget alert does not impose a hard spending cap. Gemini quota/billing may be managed separately through your API project.

## 2. Open the code in Cloud Shell

Use the Cloud Shell terminal in Google Cloud Console. Upload/extract this project or clone your GitHub repository. Run all commands from the directory containing `Dockerfile` and `cloudbuild.yaml`.

Set these non-secret values, replacing the examples:

```bash
export LEDGER_PROJECT="your-project-id"
export LEDGER_REGION="asia-south1"
export FIREBASE_API_KEY="your-firebase-web-api-key"
export FIREBASE_AUTH_DOMAIN="your-project-id.firebaseapp.com"
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

## 3. Finish account configuration

1. In Firebase Authentication → Settings → Authorized domains, add the hostname of the printed Cloud Run web URL (without `https://`). Add your eventual custom domain too, if used.
2. Open Ledger and test **Create account**, **Log in**, **Log out** and **Forgot password**.
3. Open a second browser/incognito session and create another account. Check it cannot see the first account's invoices, files or export links.
4. Try **Try the demo** from a signed-out browser. It must have its own workspace, sample master and no access to other demos.

The web account's `roles/firebaseauth.viewer` permission allows server-side token revocation checks. Admin SDK calls bypass Firebase rules, so backend ownership checks are mandatory; the included API always derives the user path from a verified ID token or signed demo cookie.

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
- **Account login fails:** check Firebase Email/Password provider, public configuration, project identity, authorized domain and the web runtime's Firebase Auth viewer permission.
- **Scans remain empty:** inspect quality, orientation and OCR page trace. Correct manually if needed. Multi-frame TIFF preview shows the first frame; the downloaded source retains all frames.
- **Public deployment rejected:** your organization may disallow `allUsers` invoker access. Use an allowed project or ask the administrator about the intended public case-study demo.
- **GitHub trigger permission error:** use the provisioned build identity and confirm it can act as both runtime service accounts, write Artifact Registry and deploy Cloud Run.

Limits are intentionally modest: 3 worker instances, concurrency 1 per worker, 3 concurrent queue tasks, up to 250 files per upload selection, and 400 invoices per registered session. This is a small case-study workload; Firestore decisions read the session's invoice history inside a transaction. Large line-item/audit payloads can reach transaction/document size limits before the invoice-count cap. Split workloads into independent sessions where appropriate, and profile before increasing limits. Separate sessions do not share PO consumption.

## Demo retention

Demo access expires after 24 hours. Files/records are not automatically removed merely because a cookie expires. `scripts/cleanup-demos.py` lists expired demo sessions by default and only removes them with `--apply`. Run it using an administrative identity after reviewing its dry-run output; registered account sessions are excluded. If a regular cleanup schedule is desired, configure a restricted scheduled job separately. Uploaded account data otherwise persists until you deliberately remove it through administrative tooling.

This version has no enterprise role model, organization sharing, abuse-resistant public demo admission, email verification enforcement, or automatic demo-to-account migration. For wider public use add admission/rate controls, retention operations and a more granular data access design before raising quotas.

## References

- https://docs.cloud.google.com/run/docs/continuous-deployment
- https://docs.cloud.google.com/build/docs/deploying-builds/deploy-cloud-run
- https://docs.cloud.google.com/run/docs/triggering/using-tasks
- https://docs.cloud.google.com/run/docs/container-contract
- https://firebase.google.com/docs/auth/admin/verify-id-tokens
- https://ai.google.dev/gemini-api/docs/document-processing
