#!/usr/bin/env bash
# Builds the WAV files Chromium plays as a fake microphone in the e2e tests. Nothing here is
# committed (e2e/.audio is git-ignored): the audio comes from the running backend and Deezer.
#   own.wav      20 s of an indexed library song, from the backend's /api/songs/{id}/preview
#   external.wav 20 s of a Deezer preview for a song NOT in the library (AudD tier)
#   noise.wav    20 s of pink noise (no match)
# Usage: e2e/prepare-audio.sh [song_id] [deezer search query for an unindexed song]
set -euo pipefail
API="${NEXT_PUBLIC_API_URL:-http://localhost:8000}"
SONG_ID="${1:-1}"
EXT_QUERY="${2:-}"
OUT="$(dirname "$0")/.audio"
mkdir -p "$OUT"
command -v ffmpeg >/dev/null || { echo "ffmpeg is required" >&2; exit 1; }

to_wav() { ffmpeg -loglevel error -y -ss "$2" -t 20 -i "$1" -ac 1 -ar 48000 -sample_fmt s16 "$3"; }

curl -fsS "$API/api/songs/$SONG_ID/preview" -o "$OUT/own.src"
to_wav "$OUT/own.src" 4 "$OUT/own.wav"

ffmpeg -loglevel error -y -f lavfi -i "anoisesrc=color=pink:amplitude=0.3:duration=20" -ac 1 -ar 48000 -sample_fmt s16 "$OUT/noise.wav"

if [ -n "$EXT_QUERY" ]; then
  url=$(curl -fsS "https://api.deezer.com/search?q=$(python3 -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1]))' "$EXT_QUERY")&limit=1" \
    | python3 -c 'import sys,json;d=json.load(sys.stdin)["data"];print(d[0]["preview"] if d else "")')
  [ -n "$url" ] || { echo "no Deezer preview for: $EXT_QUERY" >&2; exit 1; }
  curl -fsS "$url" -o "$OUT/external.src"
  to_wav "$OUT/external.src" 3 "$OUT/external.wav"
fi
rm -f "$OUT"/*.src
ls -la "$OUT"
