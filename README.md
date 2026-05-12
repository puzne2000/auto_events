# watch_folder — drop a document, get a calendar invitation

Drop a PDF, Word doc, image, or text file into this folder. `fswatch` detects it, `activate.py` fires, Codex reads the file and writes an RFC 5545 `.ics` file next to it. If the event has multiple attendees you get a small window to review the list before Calendar opens.

---

## How it works

`watch.sh` runs a continuous `fswatch` loop that filters for supported file extensions and calls `activate.py` (with a 1-second delay to let the file settle). `activate.py` sends the file to the Codex CLI with a prompt instructing it to produce a valid `.ics`. If Codex succeeds, the file is opened in Calendar. If there are two or more attendees, a dialog lets you deselect anyone before the file is opened.

---

## Architecture

```
watch.sh          fswatch loop — detects new files, filters by extension, calls activate.py
activate.py       orchestrator — notifies, runs Codex, parses attendees, filters .ics, opens file
AGENTS.md         instructions Codex follows when generating the .ics
scripts/
  extract_pdf_text.py        basic PDF text extraction (stdlib only)
  extract_pdf_text_fitz.py   cleaner PDF extraction via PyMuPDF
  extract_docx_text.py       DOCX → plain text
  ocr_pdf_text.py            OCR fallback for scanned PDFs (PyMuPDF + tesseract)
LaunchAgent       com.guykindler.activate-watch — keeps watch.sh running at login
```

---

## Prerequisites

- **macOS** — uses `fswatch`, LaunchAgents, and `open`
- **fswatch**: `brew install fswatch`
- **OpenAI `codex` CLI** with a valid API key
- **Python 3** at `/usr/bin/python3` (system install) — tkinter is included, no extras required for basic use
- Optional: **`terminal-notifier`** (`brew install terminal-notifier`) for nicer macOS notifications
- Optional: **`tesseract` + language data** (`brew install tesseract tesseract-lang`) for OCR on scanned PDFs and Hebrew PDFs with bad embedded text
- Optional: **PyMuPDF** (`pip install pymupdf` inside `.venv`) for cleaner PDF text extraction

---

## Installation

**1. Clone the repo into the watch folder location**

```bash
git clone <repo-url> "/Users/guykindler/My Drive/python stuff/watch_folder"
```

**2. Create `.env` in the repo root**

```
OPENAI_API_KEY=your_key_here
```

No quotes, no extra spaces.

**3. Copy `watch.sh` to `~/bin/`**

```bash
mkdir -p ~/bin
cp watch.sh ~/bin/watch.sh
chmod +x ~/bin/watch.sh
```

Or symlink it, or update the plist below to point directly into the repo.

**4. Create the LaunchAgent plist**

Save the following to `~/Library/LaunchAgents/com.guykindler.activate-watch.plist`, adjusting the paths if needed:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.guykindler.activate-watch</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>/Users/guykindler/bin/watch.sh</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/Users/guykindler/My Drive/python stuff/watch_folder/watch.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/guykindler/My Drive/python stuff/watch_folder/watch.err</string>
</dict>
</plist>
```

**5. Load the LaunchAgent**

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.guykindler.activate-watch.plist
```

---

## Usage

Drop any supported file into the folder. The `.ics` appears next to the original and opens in Calendar automatically.

**Supported types:** `.pdf` `.txt` `.doc` `.docx` `.jpg` `.jpeg` `.png` `.gif` `.webp` `.heic` `.tiff` `.bmp`

**Attendee review dialog** (appears when the event has 2 or more attendees):
- ↑ / ↓ — navigate the list
- Space — toggle ✓ / ✗
- Enter or OK — confirm and open
- Escape or Cancel — keep all attendees

---

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | — | Required for Codex |
| `CODEX_BIN` | `codex` | Path to the Codex binary |
| `CODEX_FLAGS` | `--full-auto --skip-git-repo-check` | Flags passed to `codex exec` |
| `CODEX_HOME` | `.codex/` in repo root | Codex state directory |

All variables can be set in `.env` in the repo root or in the shell environment.

---

## Troubleshooting

- **Watcher not running** — check status:
  ```bash
  launchctl print gui/$(id -u)/com.guykindler.activate-watch
  ```
  Reload after any change to `watch.sh` or the plist:
  ```bash
  launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.guykindler.activate-watch.plist
  launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.guykindler.activate-watch.plist
  ```

- **No `.ics` created** — read the `failure` file in the folder for the full Codex output, return code, and command used.

- **Logs** — `watch.log` and `watch.err` in the folder capture stdout/stderr from `watch.sh`.

- **File not triggering** — only top-level files with supported extensions are processed; subfolders are ignored.

- **`fswatch` not found** — `brew install fswatch`

- **Codex auth errors** — confirm `OPENAI_API_KEY` is set in `.env` with no quotes or extra spaces.
