#!/usr/bin/env bash
# Serves the static site at http://localhost:8766 (open it in your browser).
cd "$(dirname "$0")/.."
python3 -m http.server 8766 --directory public
