#! /bin/bash

# Arrêt au premier échec, variable non définie comprise : un `up` lancé
# après un `down` raté redéploierait sur une pile à moitié arrêtée.
set -euo pipefail

echo "Starting deployment process..."

echo "Deploying at $(date)..."

docker compose down
docker compose up --build -d
