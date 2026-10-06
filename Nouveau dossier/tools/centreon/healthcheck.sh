#!/bin/bash
# Healthy = the REST API answers the exact call the ETL collector makes:
# POST /centreon/api/latest/login returning an X-AUTH-TOKEN.
set -euo pipefail

PASSWORD=${CENTREON_ADMIN_PASSWORD:-Centreon!2024}

curl -fs -m 10 -X POST "http://127.0.0.1/centreon/api/latest/login" \
  -H 'Content-Type: application/json' \
  -d "{\"security\":{\"credentials\":{\"login\":\"admin\",\"password\":\"${PASSWORD}\"}}}" \
  | grep -q '"token"'
