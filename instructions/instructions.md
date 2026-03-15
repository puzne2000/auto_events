# Watch Folder Instructions

## What runs what

- `/Users/guykindler/My Drive/python stuff/watch_folder/activate.py`
  - Takes a file path as input (must be in the same folder as `activate.py`).
  - Calls the Codex CLI to generate an `.ics` file next to the input file.
  - If generation fails, writes `failure.txt` with diagnostic info.
  - On success, deletes `failure.txt` (if it exists) and opens the `.ics` file.
  - Loads environment variables from `.env` in the script folder and the current working directory.

- `/Users/guykindler/bin/watch.sh`
  - Watches the watch folder for new files.
  - Runs `activate.py` after a 1-second delay.
  - Only triggers for: `.pdf`, `.txt`, `.doc`, `.docx`, `.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`, `.heic`, `.tiff`, `.bmp` (case-insensitive).

- `/Users/guykindler/Library/LaunchAgents/com.guykindler.activate-watch.plist`
  - LaunchAgent that starts `watch.sh` on login and keeps it running.
  - Logs stdout to `watch.log` and stderr to `watch.err` in the watch folder.

## What should be running

- `com.guykindler.activate-watch`
  - The LaunchAgent that runs `watch.sh` continuously in the background.

## How to start/stop/reload the watcher

- Start (or reload after changes):
  ```bash
  launchctl bootout gui/$(id -u) /Users/guykindler/Library/LaunchAgents/com.guykindler.activate-watch.plist
  launchctl bootstrap gui/$(id -u) /Users/guykindler/Library/LaunchAgents/com.guykindler.activate-watch.plist
  ```

- Stop (disable):
  ```bash
  launchctl bootout gui/$(id -u) /Users/guykindler/Library/LaunchAgents/com.guykindler.activate-watch.plist
  ```

- Status:
  ```bash
  launchctl print gui/$(id -u)/com.guykindler.activate-watch
  ```

## How to change behavior

- Edit `watch.sh` to:
  - Change the watch folder.
  - Change file types.
  - Adjust the delay.

- Edit `activate.py` to:
  - Change how Codex is invoked.
  - Change how output is named or handled.
  - Change post-processing (e.g., opening the file).

After any change to `watch.sh` or the plist, reload the LaunchAgent (see above).

## Cancel or remove everything

1. Stop the LaunchAgent:
   ```bash
   launchctl bootout gui/$(id -u) /Users/guykindler/Library/LaunchAgents/com.guykindler.activate-watch.plist
   ```

2. Delete files (optional):
   ```bash
   rm /Users/guykindler/Library/LaunchAgents/com.guykindler.activate-watch.plist
   rm /Users/guykindler/bin/watch.sh
   rm -rf "/Users/guykindler/My Drive/python stuff/watch_folder/instructions"
   ```

## Troubleshooting

- Watcher not running:
  - Check status:
    ```bash
    launchctl print gui/$(id -u)/com.guykindler.activate-watch
    ```
  - Reload:
    ```bash
    launchctl bootout gui/$(id -u) /Users/guykindler/Library/LaunchAgents/com.guykindler.activate-watch.plist
    launchctl bootstrap gui/$(id -u) /Users/guykindler/Library/LaunchAgents/com.guykindler.activate-watch.plist
    ```

- No `.ics` file created:
  - Check `/Users/guykindler/My Drive/python stuff/watch_folder/failure.txt`.
  - Check logs:
    - `/Users/guykindler/My Drive/python stuff/watch_folder/watch.log`
    - `/Users/guykindler/My Drive/python stuff/watch_folder/watch.err`

- Codex auth errors (401 Unauthorized):
  - Make sure `OPENAI_API_KEY` is set in `/Users/guykindler/My Drive/python stuff/watch_folder/.env`.
  - Format should be:
    ```
    OPENAI_API_KEY=your_key_here
    ```
  - No quotes and no extra spaces.

- File not triggering:
  - Only `.pdf`, `.txt`, `.doc`, `.docx`, `.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`, `.heic`, `.tiff`, `.bmp` trigger by default.
  - Files inside subfolders are ignored.
  - There is a 1-second delay before processing.

- `fswatch` not found:
  - Install with:
    ```bash
    brew install fswatch
    ```
