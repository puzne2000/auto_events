#!/usr/bin/env bash
set -euo pipefail

export PATH="/opt/homebrew/bin:$PATH"

WATCH_DIR="/Users/guykindler/My Drive/python stuff/watch_folder"
PY="/opt/homebrew/bin/python3"
SCRIPT="$WATCH_DIR/activate.py"

# Watch for new files and run activate.py once per created file.
# "Created" alone can miss some copy methods; include Updated/Renamed.
fswatch -0 -e ".*" -i ".*" --event Created --event Updated --event Renamed "$WATCH_DIR" | while IFS= read -r -d "" path; do
  # Skip directories
  if [ -d "$path" ]; then
    continue
  fi
  # Only run on files in the top-level watch folder
  if [ "$(dirname "$path")" = "$WATCH_DIR" ]; then
    filename="$(basename "$path")"
    lower="$(printf '%s' "$filename" | tr '[:upper:]' '[:lower:]')"
    case "$lower" in
      *.pdf|*.txt|*.doc|*.docx|*.jpg|*.jpeg|*.png|*.gif|*.webp|*.heic|*.tiff|*.bmp) ;;
      *) continue ;;
    esac
    sleep 1
    "$PY" "$SCRIPT" "$path" || true
  fi
done
