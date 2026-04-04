#!/bin/sh
set -e

# Validate required environment variables
if [ -z "${GITHUB_PAT}" ]; then
  echo "ERROR: GITHUB_PAT is not set"
  exit 1
fi
if [ -z "${GH_URL}" ]; then
  echo "ERROR: GH_URL is not set"
  exit 1
fi
if [ -z "${REGISTRATION_TOKEN_API_URL}" ]; then
  echo "ERROR: REGISTRATION_TOKEN_API_URL is not set"
  exit 1
fi

echo "Fetching runner registration token..."
REGISTRATION_TOKEN=$(curl -sX POST \
  -H "Accept: application/vnd.github.v3+json" \
  -H "Authorization: Bearer ${GITHUB_PAT}" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  "${REGISTRATION_TOKEN_API_URL}" \
  | jq -r '.token')

if [ -z "${REGISTRATION_TOKEN}" ] || [ "${REGISTRATION_TOKEN}" = "null" ]; then
  echo "ERROR: Failed to fetch registration token — check GITHUB_PAT permissions"
  echo "  Required: Actions=Read, Administration=Read+Write on the repository"
  exit 1
fi

echo "Registering ephemeral runner at ${GH_URL}..."
./config.sh \
  --url "${GH_URL}" \
  --token "${REGISTRATION_TOKEN}" \
  --unattended \
  --ephemeral \
  --name "aca-runner-$(hostname)" \
  ${RUNNER_LABELS:+--labels "${RUNNER_LABELS}"}

echo "Starting runner..."
./run.sh
