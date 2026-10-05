#!/usr/bin/env bash
# Build + push one jurisdiction's jobs image and (re)point its daily
# scheduled machine at it. The jobs app has no always-on machines: the
# first run creates the scheduled machine, later runs update its image.
#   scripts/fly_jobs_schedule.sh <jurisdiction-slug> <image-label>
# Never `flyctl deploy` the jobs app without --build-only: that would create
# an always-on machine running the placeholder command.
set -euo pipefail
slug="${1:?jurisdiction slug, e.g. fairfax_county_va}"
label="${2:?image label, e.g. v12}"
root="$(cd "$(dirname "$0")/.." && pwd)"
suffix=""
[ "$slug" != "fairfax_city_va" ] && suffix=".$slug"
toml="fly${suffix}.toml"
app="$(grep -m1 '^app = ' "$root/ingestion/$toml" | sed 's/app = "\(.*\)"/\1/')"
cd "$root/ingestion"
flyctl deploy -c "$toml" --build-only --push --image-label "$label" .
image="registry.fly.io/$app:$label"
existing="$(flyctl machine list -a "$app" --json | python3 -c '
import json, sys
for m in json.load(sys.stdin):
    if (m.get("config") or {}).get("schedule"):
        print(m["id"]); break')"
if [ -n "$existing" ]; then
  flyctl machine update "$existing" -a "$app" --image "$image" --yes
else
  flyctl machine run "$image" -a "$app" --schedule daily --vm-cpus 4 --vm-memory 4096 \
    -e JURISDICTION="$slug" -e JURISDICTIONS_DIR=/app/jurisdictions \
    -e TRANSCRIBE_BACKEND=faster-whisper -e WHISPER_MODEL=distil-large-v3 \
    -e HF_HOME=/tmp/hf -e DATA_DIR=/tmp/data -e RAW_DATA_DIR=/tmp/data/raw \
    --restart no -- python -m councilhound.cli daily
fi
