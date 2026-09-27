#!/bin/sh
# Update the docker compose installation to a new version, safely:  sh deploy/update-docker.sh
#   1. a backup of all the data first (if it fails, nothing is changed);
#   2. the new version from GitHub, built and started (the database changes run by themselves).
# Tip: try a new version on a test copy first (docs/deployment.md, "Test copy").
set -e
cd "$(dirname "$0")/.."
docker compose exec -T web python manage.py backup --no-files
before=$(git rev-parse HEAD)
git pull
docker compose up -d --build
echo
echo "Update done. If something is wrong with the new version, go back with:"
echo "  git checkout $before && docker compose up -d --build"
echo "and put back the data of before the update with the newest ZIP in ./backups:"
echo "  docker compose exec web python manage.py restore_backup /app/backups/backup_....zip --yes"
