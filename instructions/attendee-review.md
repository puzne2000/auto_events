# Attendee Review Feature

After Codex generates the `.ics` file, `activate.py` parses the attendees and (when
there are 2 or more) shows a tkinter window so you can remove participants before the
file is opened.

## How it works

1. **Parse** — `_parse_ics_attendees` reads the `.ics` file, handles RFC 5545 line
   folding, and extracts each `ATTENDEE` as a `"Name <email>"` label.
2. **Dialog** — `_choose_attendees_to_keep` opens a small tkinter window listing all
   attendees with ✓ (keep) prefix. Use ↑↓ to navigate and Space to toggle each person
   between ✓ (keep) and ✗ (remove, shown in grey). Press Enter or click OK to confirm;
   press Escape or click Cancel to keep everyone.
3. **Filter** — `_filter_ics_attendees` rewrites the `.ics` file, removing the
   deselected `ATTENDEE` lines (including any folded continuations).
4. **Open** — the (possibly modified) `.ics` file is opened as usual.

## Behaviour details

- If the `.ics` has **no attendees** → dialog is skipped, file opens immediately.
- If the `.ics` has **exactly 1 attendee** → dialog is skipped, file opens immediately.
- If you **cancel** the dialog (Escape, Cancel button, or red ✕) → all attendees are
  kept, file opens unchanged.
- If anything goes wrong during parsing or the dialog → the error is silently ignored
  and the original file is opened unchanged (best-effort, non-blocking).

## Implementation

The three functions live in `activate.py` and are called in `main()` between the
Codex subprocess completing and the `open` call:

```python
ics_text = output_path.read_text(encoding="utf-8")
attendees = _parse_ics_attendees(ics_text)
if len(attendees) > 1:
    keep = _choose_attendees_to_keep(attendees)
else:
    keep = [a[0] for a in attendees]  # keep all, no dialog
filtered = _filter_ics_attendees(ics_text, keep, attendees)
if filtered != ics_text:
    output_path.write_text(filtered, encoding="utf-8")
```
