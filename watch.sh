#!/usr/bin/env bash
set -euo pipefail

export PATH="/opt/homebrew/bin:$PATH"

WATCH_DIR="/Users/guykindler/My Drive/python stuff/watch_folder"
ENV_FILE="$WATCH_DIR/.env"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

PY="${APP_PYTHON:-/opt/homebrew/opt/python@3.11/bin/python3.11}"
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
