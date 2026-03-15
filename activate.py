#!/usr/bin/env python3
import os
import re
import shlex
import subprocess
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


def _die(message: str, code: int = 1) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(code)


def _load_dotenv(env: dict, dotenv_path: Path) -> None:
    if not dotenv_path.is_file():
        return
    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in env:
            env[key] = value


def _parse_ics_attendees(ics_text: str) -> list[tuple[str, str]]:
    """Return list of (display_label, unfolded_line) for each ATTENDEE in the ics."""
    unfolded = re.sub(r"\r?\n[ \t]", "", ics_text)
    attendees = []
    for line in unfolded.splitlines():
        if not re.match(r"ATTENDEE[;:]", line, re.IGNORECASE):
            continue
        cn_match = re.search(r"CN=([^;:]+)", line, re.IGNORECASE)
        email_match = re.search(r":mailto:(.+)$", line, re.IGNORECASE)
        cn = cn_match.group(1).strip().strip('"') if cn_match else ""
        email = email_match.group(1).strip() if email_match else ""
        if cn and email:
            label = f"{cn} <{email}>"
        elif email:
            label = email
        elif cn:
            label = cn
        else:
            continue
        attendees.append((label, line))
    return attendees


def _choose_attendees_to_keep(attendees: list[tuple[str, str]]) -> list[str]:
    """Show a tkinter dialog with arrow-key navigation and spacebar toggle.
    Returns labels the user chose to keep. Falls back to keeping all if cancelled."""
    import tkinter as tk
    labels = [a[0] for a in attendees]
    kept = [True] * len(labels)

    root = tk.Tk()
    root.title("Review Attendees")
    root.resizable(False, False)
    root.lift()
    root.attributes("-topmost", True)
    root.focus_force()

    tk.Label(
        root,
        text="Select attendees to include:\n(↑↓ navigate · Space toggle · Enter confirm)",
        justify=tk.LEFT, padx=10, pady=8,
    ).pack()

    frame = tk.Frame(root)
    frame.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)
    listbox = tk.Listbox(frame, height=min(len(labels), 10), width=52,
                         selectmode=tk.BROWSE, activestyle="dotbox")
    sb = tk.Scrollbar(frame, orient=tk.VERTICAL, command=listbox.yview)
    listbox.configure(yscrollcommand=sb.set)

    def refresh(preserve_idx=0):
        listbox.delete(0, tk.END)
        for i, label in enumerate(labels):
            listbox.insert(tk.END, ("✓  " if kept[i] else "✗  ") + label)
            if not kept[i]:
                listbox.itemconfig(i, fg="gray")
        listbox.select_set(preserve_idx)
        listbox.activate(preserve_idx)

    refresh()
    listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    sb.pack(side=tk.RIGHT, fill=tk.Y)

    def toggle(event=None):
        sel = listbox.curselection()
        if not sel:
            return "break"
        i = sel[0]
        kept[i] = not kept[i]
        refresh(preserve_idx=i)
        return "break"

    listbox.bind("<space>", toggle)
    listbox.focus_set()

    result: list[str] = []

    def on_ok(event=None):
        result.extend(labels[i] for i, k in enumerate(kept) if k)
        root.destroy()

    def on_cancel(event=None):
        result.extend(labels)
        root.destroy()

    btn = tk.Frame(root)
    btn.pack(pady=8)
    tk.Button(btn, text="OK", width=10, command=on_ok).pack(side=tk.LEFT, padx=5)
    tk.Button(btn, text="Cancel", width=10, command=on_cancel).pack(side=tk.LEFT, padx=5)
    root.bind("<Return>", on_ok)
    root.bind("<Escape>", on_cancel)
    root.mainloop()
    return result if result else labels


def _filter_ics_attendees(
    ics_text: str,
    keep_labels: list[str],
    all_attendees: list[tuple[str, str]],
) -> str:
    """Remove ATTENDEE lines (and their RFC 5545 folded continuations) not in keep_labels."""
    remove_set = {line for label, line in all_attendees if label not in keep_labels}
    if not remove_set:
        return ics_text

    raw_lines = ics_text.splitlines(keepends=True)
    result: list[str] = []
    current_logical = ""
    current_raw: list[str] = []

    def flush() -> None:
        if current_raw and current_logical not in remove_set:
            result.extend(current_raw)

    for raw_line in raw_lines:
        content = raw_line.rstrip("\r\n")
        if content and content[0] in (" ", "\t"):
            # Continuation of the current logical line.
            current_logical += content[1:]
            current_raw.append(raw_line)
        else:
            flush()
            current_logical = content
            current_raw = [raw_line]

    flush()
    return "".join(result)


def main() -> int:
    if len(sys.argv) != 2:
        _die("Usage: activate.py <input-file>", 2)

    script_dir = Path(__file__).resolve().parent
    input_arg = Path(sys.argv[1]).expanduser()
    input_path = (script_dir / input_arg).resolve() if not input_arg.is_absolute() else input_arg.resolve()

    if input_path.parent != script_dir:
        _die("Input file must be in the same folder as activate.py.", 2)

    if not input_path.is_file():
        _die(f"Input file does not exist: {input_path}", 2)

    # Best-effort macOS notification so you can see the watcher fired.
    try:
        notifier = shutil.which("terminal-notifier")
        if notifier:
            subprocess.run(
                [
                    notifier,
                    "-title",
                    "ICS generator started",
                    "-message",
                    input_path.name,
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            # Fallback: brief dialog (more reliable than Notification Center).
            subprocess.run(
                [
                    "osascript",
                    "-e",
                    f'display dialog "{input_path.name}" with title "ICS generator started" giving up after 2',
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except Exception:
        pass

    codex_bin = os.environ.get("CODEX_BIN", "codex")
    codex_flags = os.environ.get("CODEX_FLAGS", "--full-auto --skip-git-repo-check").strip()
    codex_args = [codex_bin, "exec"] + (shlex.split(codex_flags) if codex_flags else [])

    env = os.environ.copy()
    _load_dotenv(env, script_dir / ".env")
    _load_dotenv(env, Path.cwd() / ".env")
    codex_home = env.get("CODEX_HOME")
    if not codex_home:
        codex_home = str(script_dir / ".codex")
        env["CODEX_HOME"] = codex_home
    Path(codex_home).mkdir(parents=True, exist_ok=True)

    output_path = input_path.with_suffix(".ics")

    prompt = (
        f"Generate an iCalendar (.ics) file from {input_path.name} and save it as "
        f"{output_path.name} in the same folder. Use valid RFC 5545 format. "
        f"Set METHOD:REQUEST so the event is an invitation. "
        f"Overwrite {output_path.name} if it already exists. Do not ask questions."
        f" Use AGENTS.md for instructions."
    )

    result = subprocess.run(
        codex_args + [prompt],
        cwd=str(script_dir),
        env=env,
        text=True,
        capture_output=True,
    )

    if not output_path.is_file():
        # Use a suffix that won't be picked up by watch.sh's extensions filter.
        failure_path = script_dir / "failure"
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        details = [
            f"timestamp_utc: {timestamp}",
            f"input_file: {input_path.name}",
            f"expected_output: {output_path.name}",
            f"command: {' '.join(codex_args)}",
            f"return_code: {result.returncode}",
            "stdout:",
            (result.stdout or "").strip(),
            "stderr:",
            (result.stderr or "").strip(),
            "",
        ]
        failure_path.write_text("\n".join(details), encoding="utf-8")
        return result.returncode if result.returncode != 0 else 3

    failure_path = script_dir / "failure.failure.txt"
    if failure_path.exists():
        failure_path.unlink()
    print(f"Created {output_path.name}")

    # Let the user review and trim attendees before opening.
    try:
        ics_text = output_path.read_text(encoding="utf-8")
        attendees = _parse_ics_attendees(ics_text)
        if len(attendees) > 1:
            keep = _choose_attendees_to_keep(attendees)
        else:
            keep = [a[0] for a in attendees]  # keep all, no dialog
            filtered = _filter_ics_attendees(ics_text, keep, attendees)
            if filtered != ics_text:
                output_path.write_text(filtered, encoding="utf-8")
    except Exception:
        pass  # best-effort; don't block opening the file

    try:
        subprocess.run(["open", str(output_path)], check=False)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
