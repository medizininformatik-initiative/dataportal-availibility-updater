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


python src/py/generate_availability.py \
  --onto-repo "$ONTO_REPO" \
  --onto-git-tag "$ONTO_GIT_TAG" \
  --ontology-dir "$ONTOLOGY_DIR" \
  --update-ontology "$UPDATE_ONTOLOGY" \
  --availability-master-ident "$AVAILABILITY_MASTER_IDENT" \
  --availability-input-dir "$AVAILABILITY_INPUT_DIR" \
  --availability-output-dir "$AVAILABILITY_OUTPUT_DIR" \
  --availability-report-server-base-url "$AVAILABILITY_REPORT_SERVER_BASE_URL" \
  --es-base-url "$ES_BASE_URL" \
  --es-index "$ES_INDEX" \
  --min-n-reports "$MIN_N_REPORTS" \
  --loglevel "$LOGLEVEL"

