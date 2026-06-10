#!/usr/bin/env python3
from __future__ import annotations
import os
import re
import shlex
import subprocess
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".heic",
    ".tiff",
    ".bmp",
}


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


def _choose_attendees_safe(attendees: list[tuple[str, str]]) -> list[str]:
    """Run the tkinter dialog in a subprocess so a GUI crash (SIGABRT) can't kill the parent."""
    import multiprocessing as mp

    def _worker(attendees: list[tuple[str, str]], q: "mp.Queue[list[str]]") -> None:
        try:
            q.put(_choose_attendees_to_keep(attendees))
        except Exception:
            q.put([a[0] for a in attendees])

    q: "mp.Queue[list[str]]" = mp.Queue()
    p = mp.Process(target=_worker, args=(attendees, q))
    p.start()
    p.join()
    if p.exitcode != 0 or q.empty():
        return [a[0] for a in attendees]
    return q.get()


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


def _text_quality_score(text: str) -> int:
    stripped = text.strip()
    if len(stripped) < 80:
        return 0

    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    single_char_lines = sum(1 for line in lines if len(line) <= 2)
    emails = len(re.findall(r"[\w.+-]+@[\w.-]+\.\w+", stripped))
    times = len(re.findall(r"\b\d{1,2}:\d{2}\b", stripped))
    dates = len(re.findall(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)", stripped, re.I))
    wordish = len(re.findall(r"[A-Za-z0-9\u0590-\u05FF]{2,}", stripped))
    hebrew_chars = len(re.findall(r"[\u0590-\u05FF]", stripped))

    score = len(stripped) + (wordish * 12) + (emails * 180) + (times * 80) + (dates * 80)
    score += min(hebrew_chars, 300)
    score -= single_char_lines * 35
    if len(stripped) < 300:
        score -= 250
    return max(score, 0)


def _run_text_extractor(script_dir: Path, script_name: str, input_path: Path) -> tuple[str, str]:
    script_path = script_dir / "scripts" / script_name
    result = subprocess.run(
        [sys.executable, str(script_path), str(input_path)],
        cwd=str(script_dir),
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return "", (result.stderr or result.stdout or "").strip()
    return result.stdout or "", ""


def _run_tesseract(image_path: Path, output_base: Path) -> tuple[str, str]:
    tesseract = Path("/opt/homebrew/bin/tesseract")
    if not tesseract.is_file():
        return "", f"tesseract not found at {tesseract}"

    output_txt = output_base.with_suffix(".txt")
    result = subprocess.run(
        [
            str(tesseract),
            str(image_path),
            str(output_base),
            "-l",
            "heb+eng",
            "--psm",
            "6",
        ],
        text=True,
        capture_output=True,
    )
    if result.returncode != 0 or not output_txt.is_file():
        return "", (result.stderr or result.stdout or "").strip()
    return output_txt.read_text(encoding="utf-8", errors="replace"), ""


def _convert_image_to_png(input_path: Path, output_path: Path) -> str:
    sips = shutil.which("sips")
    if not sips:
        return "sips not found"

    result = subprocess.run(
        [sips, "-s", "format", "png", str(input_path), "--out", str(output_path)],
        text=True,
        capture_output=True,
    )
    if result.returncode != 0 or not output_path.is_file():
        return (result.stderr or result.stdout or "").strip()
    return ""


def _prepare_image_text(input_path: Path, script_dir: Path) -> Path | None:
    if input_path.suffix.lower() not in IMAGE_EXTENSIONS:
        return None

    text_dir = script_dir / "text_versions"
    text_dir.mkdir(exist_ok=True)
    output_path = text_dir / f"{input_path.stem}_image_extracted.txt"

    attempts: list[tuple[str, str, int, str]] = []
    direct_text, direct_error = _run_tesseract(input_path, text_dir / f"{input_path.stem}_image_direct")
    attempts.append(("tesseract", direct_text, _text_quality_score(direct_text), direct_error))

    best_score = max((attempt[2] for attempt in attempts), default=0)
    best_chars = max((len(attempt[1].strip()) for attempt in attempts), default=0)
    if best_score < 1800 or best_chars < 120:
        converted_path = text_dir / f"{input_path.stem}_ocr_input.png"
        convert_error = _convert_image_to_png(input_path, converted_path)
        if convert_error:
            attempts.append(("sips-convert+tesseract", "", 0, convert_error))
        else:
            converted_text, converted_error = _run_tesseract(
                converted_path,
                text_dir / f"{input_path.stem}_image_converted",
            )
            attempts.append(
                (
                    "sips-convert+tesseract",
                    converted_text,
                    _text_quality_score(converted_text),
                    converted_error,
                )
            )

    selected = max(attempts, key=lambda attempt: attempt[2], default=("none", "", 0, ""))
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    report = [
        f"source_file: {input_path.name}",
        f"timestamp_utc: {timestamp}",
        f"selected_method: {selected[0]}",
        f"selected_score: {selected[2]}",
        "attempts:",
    ]
    for label, text, score, error in attempts:
        detail = f"- {label}: score={score}, chars={len(text.strip())}"
        if error:
            detail += f", error={error}"
        report.append(detail)

    report.extend(["", "selected_text:", selected[1].strip(), ""])
    output_path.write_text("\n".join(report), encoding="utf-8")
    return output_path


def _prepare_pdf_text(input_path: Path, script_dir: Path) -> Path | None:
    if input_path.suffix.lower() != ".pdf":
        return None

    text_dir = script_dir / "text_versions"
    text_dir.mkdir(exist_ok=True)
    output_path = text_dir / f"{input_path.stem}_extracted.txt"
    ocr_candidate_path = text_dir / f"{input_path.stem}_ocr_candidate.txt"

    attempts: list[tuple[str, str, int, str]] = []
    for label, script_name in (
        ("pymupdf", "extract_pdf_text_fitz.py"),
        ("pdf-stream-heuristic", "extract_pdf_text.py"),
    ):
        text, error = _run_text_extractor(script_dir, script_name, input_path)
        attempts.append((label, text, _text_quality_score(text), error))

    best_score = max((attempt[2] for attempt in attempts), default=0)
    best_chars = max((len(attempt[1].strip()) for attempt in attempts), default=0)
    if best_score < 1800 or best_chars < 500:
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(script_dir / "scripts" / "ocr_pdf_text.py"),
                    str(input_path),
                    "-o",
                    str(ocr_candidate_path),
                    "--lang",
                    "heb+eng",
                ],
                cwd=str(script_dir),
                text=True,
                capture_output=True,
            )
            if result.returncode == 0 and ocr_candidate_path.is_file():
                text = ocr_candidate_path.read_text(encoding="utf-8", errors="replace")
                attempts.append(("ocr", text, _text_quality_score(text), ""))
            else:
                attempts.append(("ocr", "", 0, (result.stderr or result.stdout or "").strip()))
        except Exception as exc:
            attempts.append(("ocr", "", 0, str(exc)))

    selected = max(attempts, key=lambda attempt: attempt[2], default=("none", "", 0, ""))
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    report = [
        f"source_file: {input_path.name}",
        f"timestamp_utc: {timestamp}",
        f"selected_method: {selected[0]}",
        f"selected_score: {selected[2]}",
        "attempts:",
    ]
    for label, text, score, error in attempts:
        detail = f"- {label}: score={score}, chars={len(text.strip())}"
        if error:
            detail += f", error={error}"
        report.append(detail)

    report.extend(["", "selected_text:", selected[1].strip(), ""])
    output_path.write_text("\n".join(report), encoding="utf-8")
    return output_path


def _prepare_extracted_text(input_path: Path, script_dir: Path) -> Path | None:
    return _prepare_pdf_text(input_path, script_dir) or _prepare_image_text(input_path, script_dir)


def _write_failure(
    script_dir: Path,
    input_path: Path,
    output_path: Path,
    codex_args: list[str],
    return_code: int,
    stdout: str = "",
    stderr: str = "",
) -> None:
    # Use a suffixless file so watch.sh won't pick it up as another input.
    failure_path = script_dir / "failure"
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    details = [
        f"timestamp_utc: {timestamp}",
        f"input_file: {input_path.name}",
        f"expected_output: {output_path.name}",
        f"command: {' '.join(codex_args)}",
        f"return_code: {return_code}",
        "stdout:",
        stdout.strip(),
        "stderr:",
        stderr.strip(),
        "",
    ]
    failure_path.write_text("\n".join(details), encoding="utf-8")


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

    env = os.environ.copy()
    _load_dotenv(env, script_dir / ".env")
    _load_dotenv(env, Path.cwd() / ".env")
    codex_bin = env.get("CODEX_BIN", "codex")
    codex_flags = env.get("CODEX_FLAGS", "--sandbox workspace-write --skip-git-repo-check").strip()
    codex_args = [codex_bin, "exec"] + (shlex.split(codex_flags) if codex_flags else [])
    codex_home = env.get("CODEX_HOME")
    if not codex_home:
        codex_home = str(script_dir / ".codex")
        env["CODEX_HOME"] = codex_home
    Path(codex_home).mkdir(parents=True, exist_ok=True)

    output_path = input_path.with_suffix(".ics")
    extracted_text_path = _prepare_extracted_text(input_path, script_dir)
    extraction_instruction = ""
    if extracted_text_path:
        extraction_instruction = (
            f" A pre-extracted text version is available at {extracted_text_path.relative_to(script_dir)}. "
            "Use it as the primary text source, especially if direct file reading is garbled. "
            "It includes extraction method and quality metadata."
        )

    prompt = (
        f"Generate an iCalendar (.ics) file from {input_path.name} and save it as "
        f"{output_path.name} in the same folder. Use valid RFC 5545 format. "
        f"Set METHOD:REQUEST so the event is an invitation. "
        f"Overwrite {output_path.name} if it already exists. Do not ask questions."
        f"{extraction_instruction} Use AGENTS.md for instructions."
    )

    codex_path = shutil.which(codex_bin, path=env.get("PATH")) if not Path(codex_bin).is_absolute() else codex_bin
    if not codex_path or not Path(codex_path).is_file() or not os.access(codex_path, os.X_OK):
        _write_failure(
            script_dir,
            input_path,
            output_path,
            codex_args,
            127,
            stderr=f"Codex binary not found or not executable: {codex_bin}",
        )
        return 127

    try:
        result = subprocess.run(
            codex_args + [prompt],
            cwd=str(script_dir),
            env=env,
            text=True,
            capture_output=True,
        )
    except FileNotFoundError as exc:
        _write_failure(
            script_dir,
            input_path,
            output_path,
            codex_args,
            127,
            stderr=str(exc),
        )
        return 127

    if not output_path.is_file():
        _write_failure(
            script_dir,
            input_path,
            output_path,
            codex_args,
            result.returncode,
            result.stdout or "",
            result.stderr or "",
        )
        return result.returncode if result.returncode != 0 else 3

    for failure_path in (script_dir / "failure", script_dir / "failure.failure.txt"):
        if failure_path.exists():
            failure_path.unlink()
    print(f"Created {output_path.name}")

    # Let the user review and trim attendees before opening.
    try:
        ics_text = output_path.read_text(encoding="utf-8")
        attendees = _parse_ics_attendees(ics_text)
        if len(attendees) > 1:
            keep = _choose_attendees_safe(attendees)
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
