#!/usr/bin/env bash
# Run in Google Cloud Shell from the repository root after reading docs/DEPLOY.md.
# This provisions billable resources in the explicitly selected project.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${LEDGER_PROJECT:?Set LEDGER_PROJECT to your Google Cloud project ID}"
: "${FIREBASE_API_KEY:?Set FIREBASE_API_KEY to your Firebase web app public API key}"
export LEDGER_REGION="${LEDGER_REGION:-asia-south1}"
export LEDGER_BUCKET="${LEDGER_BUCKET:-${LEDGER_PROJECT}-ledger-invoices}"
export FIREBASE_AUTH_DOMAIN="${FIREBASE_AUTH_DOMAIN:-${LEDGER_PROJECT}.firebaseapp.com}"
export LEDGER_PROJECT
printf 'Setting up Ledger in project %s, region %s. Billing must be enabled.\n' "$LEDGER_PROJECT" "$LEDGER_REGION"
gcloud config set project "$LEDGER_PROJECT"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com firestore.googleapis.com storage.googleapis.com cloudtasks.googleapis.com secretmanager.googleapis.com identitytoolkit.googleapis.com firebase.googleapis.com
for account in ledger-web ledger-worker ledger-tasks ledger-build; do
  if ! gcloud iam service-accounts describe "$account@$LEDGER_PROJECT.iam.gserviceaccount.com" >/dev/null 2>&1; then
    gcloud iam service-accounts create "$account" --display-name="$account"
  fi
done
for account in ledger-web ledger-worker; do
  gcloud projects add-iam-policy-binding "$LEDGER_PROJECT" --member="serviceAccount:$account@$LEDGER_PROJECT.iam.gserviceaccount.com" --role=roles/datastore.user --condition=None --quiet >/dev/null
done
gcloud projects add-iam-policy-binding "$LEDGER_PROJECT" --member="serviceAccount:ledger-web@$LEDGER_PROJECT.iam.gserviceaccount.com" --role=roles/firebaseauth.viewer --condition=None --quiet >/dev/null
gcloud projects add-iam-policy-binding "$LEDGER_PROJECT" --member="serviceAccount:ledger-web@$LEDGER_PROJECT.iam.gserviceaccount.com" --role=roles/cloudtasks.enqueuer --condition=None --quiet >/dev/null
if ! gcloud storage buckets describe "gs://$LEDGER_BUCKET" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://$LEDGER_BUCKET" --location="$LEDGER_REGION" --uniform-bucket-level-access --public-access-prevention
fi
gcloud storage buckets add-iam-policy-binding "gs://$LEDGER_BUCKET" --member="serviceAccount:ledger-web@$LEDGER_PROJECT.iam.gserviceaccount.com" --role=roles/storage.objectUser >/dev/null
gcloud storage buckets add-iam-policy-binding "gs://$LEDGER_BUCKET" --member="serviceAccount:ledger-worker@$LEDGER_PROJECT.iam.gserviceaccount.com" --role=roles/storage.objectViewer >/dev/null
if ! gcloud firestore databases describe --database='(default)' >/dev/null 2>&1; then
  gcloud firestore databases create --database='(default)' --location="$LEDGER_REGION" --type=firestore-native
fi
if ! gcloud artifacts repositories describe ledger --location="$LEDGER_REGION" >/dev/null 2>&1; then
  gcloud artifacts repositories create ledger --location="$LEDGER_REGION" --repository-format=docker
fi
if ! gcloud tasks queues describe ledger-invoices --location="$LEDGER_REGION" >/dev/null 2>&1; then
  gcloud tasks queues create ledger-invoices --location="$LEDGER_REGION" --max-concurrent-dispatches=3 --max-dispatches-per-second=1 --max-attempts=6 --min-backoff=60s --max-backoff=600s
fi
# Allow only the app identity to enqueue tasks as the dedicated task identity.
gcloud iam service-accounts add-iam-policy-binding "ledger-tasks@$LEDGER_PROJECT.iam.gserviceaccount.com" --member="serviceAccount:ledger-web@$LEDGER_PROJECT.iam.gserviceaccount.com" --role=roles/iam.serviceAccountUser --quiet >/dev/null
project_number="$(gcloud projects describe "$LEDGER_PROJECT" --format='value(projectNumber)')"
gcloud beta services identity create --service=cloudtasks.googleapis.com --project="$LEDGER_PROJECT" >/dev/null
gcloud iam service-accounts add-iam-policy-binding "ledger-tasks@$LEDGER_PROJECT.iam.gserviceaccount.com" --member="serviceAccount:service-$project_number@gcp-sa-cloudtasks.iam.gserviceaccount.com" --role=roles/iam.serviceAccountTokenCreator --quiet >/dev/null
# Keys are entered privately and piped directly to Secret Manager, never to disk.
if ! gcloud secrets describe ledger-session-secret >/dev/null 2>&1; then
  python3 -c 'import secrets;print(secrets.token_urlsafe(48),end="")' | gcloud secrets create ledger-session-secret --data-file=- --replication-policy=automatic
fi
if ! gcloud secrets describe ledger-gemini-key >/dev/null 2>&1; then
  read -r -s -p 'Gemini API key (leave empty to use OCR fallback only): ' ledger_gemini_key
  printf '\n'
  # A whitespace value acts as an invalid key and demonstrates fallback if skipped.
  printf '%s' "${ledger_gemini_key:- }" | gcloud secrets create ledger-gemini-key --data-file=- --replication-policy=automatic
  unset ledger_gemini_key
fi
for account in ledger-web ledger-worker; do
  for secret in ledger-session-secret ledger-gemini-key; do
    gcloud secrets add-iam-policy-binding "$secret" --member="serviceAccount:$account@$LEDGER_PROJECT.iam.gserviceaccount.com" --role=roles/secretmanager.secretAccessor --quiet >/dev/null
  done
done
# Bootstrap build includes OCR and the complete local regression suite.
build_id="$(gcloud builds submit --async --config=cloudbuild.bootstrap.yaml --substitutions="_REGION=$LEDGER_REGION" --format='value(id)')"
printf 'Build %s is running. Waiting for the image and regression checks…\n' "$build_id"
while true; do
  build_status="$(gcloud builds describe "$build_id" --format='value(status)')"
  case "$build_status" in
    SUCCESS) break ;;
    FAILURE|INTERNAL_ERROR|TIMEOUT|CANCELLED|EXPIRED)
      gcloud builds log "$build_id"
      printf 'Build failed. No service was deployed.\n' >&2
      exit 1 ;;
  esac
  sleep 5
done
image="$LEDGER_REGION-docker.pkg.dev/$LEDGER_PROJECT/ledger/app:$build_id"
config_dir="$(mktemp -d)"
trap 'rm -rf "$config_dir"' EXIT
export LEDGER_CONFIG_DIR="$config_dir"
python3 - <<'PY'
import json,os
from pathlib import Path
p=os.environ['LEDGER_PROJECT']
base={'LEDGER_STORAGE':'cloud','GOOGLE_CLOUD_PROJECT':p,'LEDGER_BUCKET':os.environ['LEDGER_BUCKET'],
      'LEDGER_REGION':os.environ['LEDGER_REGION'],'LEDGER_QUEUE':'ledger-invoices',
      'LEDGER_TASK_SERVICE_ACCOUNT':f'ledger-tasks@{p}.iam.gserviceaccount.com','GEMINI_MODEL':'gemini-2.5-flash',
      'LEDGER_SERVICE':'worker'}
Path(os.environ['LEDGER_CONFIG_DIR'],'worker.json').write_text(json.dumps(base))
PY
gcloud run deploy ledger-worker --image="$image" --region="$LEDGER_REGION" --service-account="ledger-worker@$LEDGER_PROJECT.iam.gserviceaccount.com" --no-allow-unauthenticated --concurrency=1 --cpu=1 --memory=2Gi --timeout=1800 --min-instances=0 --max-instances=3 --env-vars-file="$config_dir/worker.json" --set-secrets=LEDGER_SESSION_SECRET=ledger-session-secret:latest,GEMINI_API_KEY=ledger-gemini-key:latest --quiet
export LEDGER_WORKER_URL="$(gcloud run services describe ledger-worker --region="$LEDGER_REGION" --format='value(status.url)')"
gcloud run services update ledger-worker --region="$LEDGER_REGION" --update-env-vars="LEDGER_WORKER_URL=$LEDGER_WORKER_URL" --quiet
gcloud run services add-iam-policy-binding ledger-worker --region="$LEDGER_REGION" --member="serviceAccount:ledger-tasks@$LEDGER_PROJECT.iam.gserviceaccount.com" --role=roles/run.invoker --quiet >/dev/null
python3 - <<'PY'
import json,os
from pathlib import Path
root=Path(os.environ['LEDGER_CONFIG_DIR']);base=json.loads((root/'worker.json').read_text())
base.update(LEDGER_SERVICE='web',LEDGER_WORKER_URL=os.environ['LEDGER_WORKER_URL'],FIREBASE_API_KEY=os.environ['FIREBASE_API_KEY'],FIREBASE_AUTH_DOMAIN=os.environ['FIREBASE_AUTH_DOMAIN'])
(root/'web.json').write_text(json.dumps(base))
PY
gcloud run deploy ledger-web --image="$image" --region="$LEDGER_REGION" --service-account="ledger-web@$LEDGER_PROJECT.iam.gserviceaccount.com" --allow-unauthenticated --concurrency=20 --cpu=1 --memory=1Gi --timeout=120 --min-instances=0 --max-instances=3 --env-vars-file="$config_dir/web.json" --set-secrets=LEDGER_SESSION_SECRET=ledger-session-secret:latest,GEMINI_API_KEY=ledger-gemini-key:latest --quiet
# Dedicated identity for future GitHub build triggers (no runtime API key access).
for role in roles/run.admin roles/artifactregistry.writer roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding "$LEDGER_PROJECT" --member="serviceAccount:ledger-build@$LEDGER_PROJECT.iam.gserviceaccount.com" --role="$role" --condition=None --quiet >/dev/null
done
for account in ledger-web ledger-worker; do
  gcloud iam service-accounts add-iam-policy-binding "$account@$LEDGER_PROJECT.iam.gserviceaccount.com" --member="serviceAccount:ledger-build@$LEDGER_PROJECT.iam.gserviceaccount.com" --role=roles/iam.serviceAccountUser --quiet >/dev/null
done
printf '\nLedger is deployed. Open this URL:\n'
gcloud run services describe ledger-web --region="$LEDGER_REGION" --format='value(status.url)'
printf '\nNext: add the web hostname to Firebase Authentication authorized domains and connect the GitHub trigger using docs/DEPLOY.md.\n'
