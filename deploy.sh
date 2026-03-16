#!/bin/bash
set -euo pipefail

echo "Deploying EduMentor Live to Google Cloud Run..."

# Set project ID (replace with your project id)
# gcloud config set project YOUR_PROJECT_ID

if [ ! -f ".env" ]; then
  echo "Error: .env file not found in project root."
  exit 1
fi

GOOGLE_API_KEY="$(grep -E '^GOOGLE_API_KEY=' .env | head -n1 | cut -d'=' -f2-)"
GOOGLE_API_KEY="${GOOGLE_API_KEY%\"}"
GOOGLE_API_KEY="${GOOGLE_API_KEY#\"}"
GOOGLE_API_KEY="${GOOGLE_API_KEY%$'\r'}"

if [ -z "${GOOGLE_API_KEY}" ]; then
  echo "Error: GOOGLE_API_KEY is missing in .env"
  exit 1
fi

gcloud run deploy edumentor-live \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --port 8080 \
  --set-env-vars AGENT_MODEL="gemini-2.5-flash-native-audio-preview-12-2025" \
  --set-env-vars "GOOGLE_API_KEY=${GOOGLE_API_KEY}"

echo "Deployment complete!"
