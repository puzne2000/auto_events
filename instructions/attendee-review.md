# Attendee Review Feature

After Codex generates the `.ics` file, `activate.py` first normalizes the organizer
to Guy Kindler (`guy.kindler@mail.huji.ac.il`). Any non-Guy organizer is converted
to an attendee, and Guy is removed from attendee lines. It then parses the attendees
and (when there are 2 or more) shows a tkinter window so you can remove participants
before the file is opened.

## How it works

1. **Normalize** — `_force_guy_as_organizer` rewrites the `.ics` so Guy is the only
   `ORGANIZER`, and all other people/lists are represented as `ATTENDEE` lines.
2. **Parse** — `_parse_ics_attendees` reads the `.ics` file, handles RFC 5545 line
   folding, and extracts each `ATTENDEE` as a `"Name <email>"` label.
3. **Dialog** — `_choose_attendees_to_keep` opens a small tkinter window listing all
   attendees with ✓ (keep) prefix. Use ↑↓ to navigate and Space to toggle each person
   between ✓ (keep) and ✗ (remove, shown in grey). Press Enter or click OK to confirm;
   press Escape or click Cancel to keep everyone.
4. **Filter** — `_filter_ics_attendees` rewrites the `.ics` file, removing the
   deselected `ATTENDEE` lines (including any folded continuations).
5. **Open** — the (possibly modified) `.ics` file is opened as usual.

## Behaviour details

- If the `.ics` has **no attendees** → dialog is skipped, file opens immediately.
- If the `.ics` has **exactly 1 attendee** → dialog is skipped, file opens immediately.
- If you **cancel** the dialog with Escape or the Cancel button → all attendees are
  kept, file opens unchanged.
- If you close the dialog with the window close button → activation fails and writes
  a `failure` file.
- If anything goes wrong during parsing or the dialog → activation fails and writes
  a `failure` file instead of opening the calendar.

## Implementation

The three functions live in `activate.py` and are called in `main()` between the
Codex subprocess completing and the `open` call:

```python
ics_text = _force_guy_as_organizer(output_path.read_text(encoding="utf-8"))
output_path.write_text(ics_text, encoding="utf-8")
attendees = _parse_ics_attendees(ics_text)
if len(attendees) > 1:
    keep = _choose_attendees_to_keep(attendees)
else:
    keep = [a[0] for a in attendees]  # keep all, no dialog
filtered = _filter_ics_attendees(ics_text, keep, attendees)
if filtered != ics_text:
    output_path.write_text(filtered, encoding="utf-8")
```
