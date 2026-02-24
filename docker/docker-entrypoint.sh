#!/bin/bash

ONTO_REPO=${ONTO_REPO:-"https://mydefault-onto-repo-url"}
ONTO_GIT_TAG=${ONTO_GIT_TAG:-"v1.0"}
ONTOLOGY_DIR=${ONTOLOGY_DIR:-"/default/ontology/dir"}
UPDATE_ONTOLOGY=${UPDATE_ONTOLOGY:-"false"}
AVAILABILITY_MASTER_IDENT=${AVAILABILITY_MASTER_IDENT:-"fdpg-data-availability-report-obfuscated"}
AVAILABILITY_INPUT_DIR=${AVAILABILITY_INPUT_DIR:-"/default/input/dir"}
AVAILABILITY_OUTPUT_DIR=${AVAILABILITY_OUTPUT_DIR:-"/default/output/dir"}
AVAILABILITY_REPORT_SERVER_BASE_URL=${AVAILABILITY_REPORT_SERVER_BASE_URL:-"https://availability-report-server"}
ES_BASE_URL=${ES_BASE_URL:-"https://elasticsearch-url"}
ES_INDEX=${ES_INDEX:-"default-index"}
MIN_N_REPORTS=${MIN_N_REPORTS:-"3"}
LOGLEVEL=${LOGLEVEL:-INFO}

# Enable oauth
USE_OAUTH2=${USE_OAUTH2:-"false"}
OAUTH_TOKEN_URL=${OAUTH_TOKEN_URL:-""}
OAUTH_CLIENT_ID=${OAUTH_CLIENT_ID:-""}
OAUTH_CLIENT_SECRET=${OAUTH_CLIENT_SECRET:-""}
OAUTH_SCOPE=${OAUTH_SCOPE:-""}

# Enable Basic Auth (true/false)
USE_BASIC_AUTH=${USE_BASIC_AUTH:-"false"}
BASIC_USERNAME=${BASIC_USERNAME:-""}
BASIC_PASSWORD=${BASIC_PASSWORD:-""}

# ------------------------------------------------------------------
# Build optional CLI flags
# ------------------------------------------------------------------

AUTH_ARGS=()

if [ "$USE_OAUTH2" = "true" ]; then
  AUTH_ARGS+=(--use-oauth2)
  AUTH_ARGS+=(--oauth-token-url "$OAUTH_TOKEN_URL")
  AUTH_ARGS+=(--oauth-client-id "$OAUTH_CLIENT_ID")
  AUTH_ARGS+=(--oauth-client-secret "$OAUTH_CLIENT_SECRET")

  if [ -n "$OAUTH_SCOPE" ]; then
    AUTH_ARGS+=(--oauth-scope "$OAUTH_SCOPE")
  fi
fi

if [ "$USE_BASIC_AUTH" = "true" ]; then
  AUTH_ARGS+=(--use-basic-auth)
  AUTH_ARGS+=(--basic-username "$BASIC_USERNAME")
  AUTH_ARGS+=(--basic-password "$BASIC_PASSWORD")
fi


CA_CERT="/opt/availability-updater/auth/cert.pem"
# Optional own ca cert
if [ -f "$CA_CERT" ]; then
  AUTH_ARGS+=(--ca-cert "$CA_CERT")
fi

if [ "$UPDATE_ONTOLOGY" = "true" ]; then
  UPDATE_ONTO="--update-ontology" 
fi


python src/py/generate_availability.py \
  --onto-repo "$ONTO_REPO" \
  --onto-git-tag "$ONTO_GIT_TAG" \
  --ontology-dir "$ONTOLOGY_DIR" \
  $UPDATE_ONTO \
  --availability-master-ident "$AVAILABILITY_MASTER_IDENT" \
  --availability-input-dir "$AVAILABILITY_INPUT_DIR" \
  --availability-output-dir "$AVAILABILITY_OUTPUT_DIR" \
  --availability-report-server-base-url "$AVAILABILITY_REPORT_SERVER_BASE_URL" \
  --es-base-url "$ES_BASE_URL" \
  --es-index "$ES_INDEX" \
  --min-n-reports "$MIN_N_REPORTS" \
  --loglevel "$LOGLEVEL" \
  "${AUTH_ARGS[@]}"
