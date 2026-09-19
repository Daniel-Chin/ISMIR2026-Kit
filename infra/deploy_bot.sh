#!/bin/bash
# Build + deploy both ISMIR Guide Cloud Run services.
#
# One-time setup (NOT repeated here): GCP project; Artifact Registry repo
# "ismir-guide"; Firestore (native mode) with a TTL policy on collection
# "jobs" field "expires_at"; Cloud Tasks queue (set queue-level max
# concurrency — this is the global concurrency cap from LLM_plan.md §9);
# catalogue GCS bucket; service accounts ismir-guide-ingress /
# ismir-guide-worker (worker SA: run.invoker on itself for Cloud Tasks OIDC,
# storage.objectViewer on the bucket, datastore.user); Secret Manager
# secrets: ismir-guide-slack-bot-token, ismir-guide-slack-signing-secret,
# ismir-guide-anthropic-key, ismir-guide-voyage-key.
#
# Usage: PROJECT=my-proj REGION=me-central1 ./infra/deploy_bot.sh
set -euo pipefail

PROJECT="${PROJECT:?set PROJECT}"
REGION="${REGION:-me-central1}"
QUEUE="${QUEUE:-ismir-guide-jobs}"
BUCKET="${BUCKET:-gs://${PROJECT}-catalogue}"
INGRESS_SA="ismir-guide-ingress@${PROJECT}.iam.gserviceaccount.com"
WORKER_SA="ismir-guide-worker@${PROJECT}.iam.gserviceaccount.com"
AGENT_MODEL="${AGENT_MODEL:-claude-sonnet-5}"
SCOPE_MODEL="${SCOPE_MODEL:-claude-haiku-4-5}"
REPO="${REGION}-docker.pkg.dev/${PROJECT}/ismir-guide"

cd "$(dirname "$0")/../bot"

# Vendor the shared schema definition into the image context (single schema
# definition lives in catalogue/schema.py — LLM_plan.md §2)
cp ../catalogue/schema.py shared/catalogue_schema.py

echo "== build images =="
gcloud builds submit . --project "$PROJECT" --region "$REGION" \
    --config ../infra/cloudbuild.yaml --substitutions "_REGION=${REGION}"

echo "== deploy worker =="
gcloud run deploy ismir-guide-worker \
    --project "$PROJECT" --region "$REGION" \
    --image "${REPO}/worker:latest" \
    --no-allow-unauthenticated \
    --service-account "$WORKER_SA" \
    --concurrency 4 --max-instances 5 --timeout 300 \
    --set-env-vars "GCP_PROJECT=${PROJECT},CATALOGUE_BUCKET=${BUCKET},AGENT_MODEL=${AGENT_MODEL},SCOPE_MODEL=${SCOPE_MODEL},MAX_DAILY_SPEND_USD=${MAX_DAILY_SPEND_USD:-20},ADMIN_USER_IDS=${ADMIN_USER_IDS:-}" \
    --set-secrets "SLACK_BOT_TOKEN=ismir-guide-slack-bot-token:latest,ANTHROPIC_API_KEY=ismir-guide-anthropic-key:latest,VOYAGE_API_KEY=ismir-guide-voyage-key:latest"

WORKER_URL=$(gcloud run services describe ismir-guide-worker \
    --project "$PROJECT" --region "$REGION" --format 'value(status.url)')

echo "== deploy ingress =="
gcloud run deploy ismir-guide-ingress \
    --project "$PROJECT" --region "$REGION" \
    --image "${REPO}/ingress:latest" \
    --allow-unauthenticated \
    --service-account "$INGRESS_SA" \
    --concurrency 80 --max-instances 3 --timeout 30 \
    --set-env-vars "GCP_PROJECT=${PROJECT},WORKER_URL=${WORKER_URL},TASKS_QUEUE=projects/${PROJECT}/locations/${REGION}/queues/${QUEUE},TASKS_SA_EMAIL=${WORKER_SA},PER_USER_DAILY_LIMIT=${PER_USER_DAILY_LIMIT:-20}" \
    --set-secrets "SLACK_BOT_TOKEN=ismir-guide-slack-bot-token:latest,SLACK_SIGNING_SECRET=ismir-guide-slack-signing-secret:latest"

echo
echo "Ingress URL (set as Slack Request URL, path /slack/events):"
gcloud run services describe ismir-guide-ingress \
    --project "$PROJECT" --region "$REGION" --format 'value(status.url)'
