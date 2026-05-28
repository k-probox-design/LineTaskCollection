#!/bin/bash
set -e

PROJECT_ID="probox-linetask-prod"
REGION="asia-northeast1"
SERVICE_NAME="linetask-receive"

gcloud run deploy ${SERVICE_NAME} \
  --source . \
  --region ${REGION} \
  --project ${PROJECT_ID} \
  --service-account "linetask-cloudrun@${PROJECT_ID}.iam.gserviceaccount.com" \
  --allow-unauthenticated \
  --set-env-vars "GCS_BUCKET=probox-linetask-prod-intake,FIRESTORE_PROJECT=${PROJECT_ID}" \
  --set-secrets "LINE_CHANNEL_SECRET=line-channel-secret:latest,LINE_CHANNEL_ACCESS_TOKEN=line-channel-access-token:latest" \
  --memory 512Mi \
  --cpu 1 \
  --max-instances 3 \
  --min-instances 1 \
  --cpu-boost \
  --timeout 60s
