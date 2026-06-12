#!/bin/bash
# Poll origin/main and redeploy when it moves. Run by a systemd timer:
# see docs/DEPLOYMENT.md ("Auto-deploy from GitHub").
set -euo pipefail

cd "$(dirname "$0")/.."

git fetch -q origin main
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" = "$REMOTE" ]; then
    exit 0
fi

echo "deploying ${REMOTE:0:7} (was ${LOCAL:0:7})"
# reset, not pull: a deploy clone tracks origin/main exactly, even across
# history rewrites or force pushes
git reset --hard -q origin/main
docker compose up -d --build
echo "deployed ${REMOTE:0:7}"
