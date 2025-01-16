#!/bin/bash
ONTO_REPO=${ONTO_REPO:-"https://mydefault-onto-repo-url"}
ONTO_GIT_TAG=${ONTO_GIT_TAG:-"v1.0"}
ONTOLOGY_DIR=${ONTOLOGY_DIR:-"/default/ontology/dir"}
UPDATE_ONTOLOGY=${UPDATE_ONTOLOGY:-"false"}
AVAILABILITY_INPUT_DIR=${AVAILABILITY_INPUT_DIR:-"/default/input/dir"}
AVAILABILITY_OUTPUT_DIR=${AVAILABILITY_OUTPUT_DIR:-"/default/output/dir"}
AVAILABILITY_REPORT_SERVER_BASE_URL=${AVAILABILITY_REPORT_SERVER_BASE_URL:-"https://availability-report-server"}
ES_BASE_URL=${ES_BASE_URL:-"https://elasticsearch-url"}
ES_INDEX=${ES_INDEX:-"default-index"}
LOGLEVEL=${LOGLEVEL:-"INFO"}



python src/py/generate-availability.py \
  --onto_repo "$ONTO_REPO" \
  --onto_git_tag "$ONTO_GIT_TAG" \
  --ontology_dir "$ONTOLOGY_DIR" \
  --update_ontology "$UPDATE_ONTOLOGY" \
  --availability_input_dir "$AVAILABILITY_INPUT_DIR" \
  --availability_output_dir "$AVAILABILITY_OUTPUT_DIR" \
  --availability_report_server_base_url "$AVAILABILITY_REPORT_SERVER_BASE_URL" \
  --es_base_url "$ES_BASE_URL" \
  --es_index "$ES_INDEX" \
  --loglevel "$LOGLEVEL"