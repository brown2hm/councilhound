#!/usr/bin/env bash
# Deploy one jurisdiction's api or web app to Fly.
#   scripts/deploy.sh <jurisdiction-slug> api|web
# The City keeps its original app names and fly.toml; every other
# jurisdiction has api/fly.<slug>.toml and frontend/fly.<slug>.toml.
set -euo pipefail
slug="${1:?jurisdiction slug, e.g. fairfax_city_va}"
target="${2:?api|web}"
root="$(cd "$(dirname "$0")/.." && pwd)"
suffix=""
[ "$slug" != "fairfax_city_va" ] && suffix=".$slug"
case "$target" in
  api) (cd "$root" && flyctl deploy -c "api/fly${suffix}.toml") ;;
  web) (cd "$root/frontend" && flyctl deploy -c "fly${suffix}.toml" --local-only) ;;
  *) echo "target must be api or web" >&2; exit 2 ;;
esac
