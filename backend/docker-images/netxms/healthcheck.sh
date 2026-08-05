#!/bin/bash
# Healthy = the Web API answers the exact call the ETL collector makes:
# POST /v1/login returning a bearer token.
set -euo pipefail

PORT=${NETXMS_WEBAPI_PORT:-8000}
PASSWORD=${NETXMS_ADMIN_PASSWORD:-netxms}

curl -fs -m 5 -X POST "http://127.0.0.1:${PORT}/v1/login" \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"admin\",\"password\":\"${PASSWORD}\"}" \
  | grep -q '"token"'
