#!/usr/bin/env bash
# Re-downloads sources (cached) and rebuilds public/data/*.json.
cd "$(dirname "$0")/.."
python3 -m engine.run
echo
echo 'Done. Restart scripts/start.sh or refresh your browser.'
