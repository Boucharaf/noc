#!/usr/bin/env bash
# Generates a self-signed TLS certificate for local/demo HTTPS termination at
# the nginx gateway (cahier des charges §10.1: "HTTPS obligatoire").
#
# This is NOT for production use against real traffic — browsers will show a
# trust warning since it's self-signed. For production, replace nginx/certs/
# with a certificate from Let's Encrypt or ANPTIC's internal CA (the domains
# below match what's referenced in the README: noc.anptic.bf / noc-api.anptic.bf).
#
# Re-run any time to regenerate (e.g. after expiry):
#   ./nginx/generate_cert.sh
set -euo pipefail

cd "$(dirname "$0")"
mkdir -p certs

openssl req -x509 -nodes -newkey rsa:2048 \
  -keyout certs/noc-selfsigned.key \
  -out certs/noc-selfsigned.crt \
  -days 825 \
  -subj "/C=BF/ST=Centre/L=Ouagadougou/O=ANPTIC/OU=NOC/CN=noc.anptic.bf" \
  -addext "subjectAltName=DNS:noc.anptic.bf,DNS:noc-api.anptic.bf,DNS:localhost,IP:127.0.0.1"

chmod 600 certs/noc-selfsigned.key
echo "Wrote nginx/certs/noc-selfsigned.crt and noc-selfsigned.key (valid 825 days)."
