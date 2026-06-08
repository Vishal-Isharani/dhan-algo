#!/bin/sh
set -e
cd /app

mkdir -p data .cache strategies/configs

# Persist manifest and strategy configs across Dokploy redeploys.
if [ ! -f data/manifest.json ]; then
  cp /app/config.defaults/manifest.json data/manifest.json
  echo "Initialized data/manifest.json from defaults."
fi
cp data/manifest.json strategies/manifest.json

if [ ! -f strategies/configs/.initialized ]; then
  cp -n /app/config.defaults/*.json strategies/configs/ 2>/dev/null || true
  touch strategies/configs/.initialized
  echo "Initialized strategy configs volume from defaults."
fi

exec "$@"
