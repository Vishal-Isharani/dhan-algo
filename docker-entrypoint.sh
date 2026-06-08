#!/bin/sh
set -e
cd /app

mkdir -p data .cache strategies/configs

sync_strategy_configs() {
  copied=0
  for f in /app/config.defaults/*.json; do
    [ -f "$f" ] || continue
    case "$f" in *.example.json) continue ;; esac
    cp -f "$f" strategies/configs/
    copied=$((copied + 1))
  done
  echo "Synced ${copied} strategy config(s) from repo (image build)."
}

# Dokploy stores manifest in the data volume, not from git directly.
# SYNC_MANIFEST_FROM_REPO=1 (default) copies the repo manifest baked into the image on each start.
SYNC_MANIFEST=${SYNC_MANIFEST_FROM_REPO:-1}
if [ "$SYNC_MANIFEST" = "1" ] || [ ! -f data/manifest.json ]; then
  cp /app/config.defaults/manifest.json data/manifest.json
  if [ "$SYNC_MANIFEST" = "1" ]; then
    echo "Synced data/manifest.json from repo (image build)."
  else
    echo "Initialized data/manifest.json from defaults."
  fi
fi
cp data/manifest.json strategies/manifest.json

SYNC_CONFIGS=${SYNC_STRATEGY_CONFIGS_FROM_REPO:-1}
if [ "$SYNC_CONFIGS" = "1" ]; then
  sync_strategy_configs
elif [ ! -f strategies/configs/.initialized ]; then
  sync_strategy_configs
  touch strategies/configs/.initialized
  echo "Initialized strategy configs volume (one-time seed)."
fi

exec "$@"
