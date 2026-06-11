#!/usr/bin/env python3
from __future__ import annotations
import hashlib
import json
import os
import re
import subprocess
import shutil
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from urllib import error as urlerror
from urllib import request

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
ORGANIZER_CN = "Guy Kindler"
ORGANIZER_EMAIL = "guy.kindler@mail.huji.ac.il"
ORGANIZER_LINE = f"ORGANIZER;CN={ORGANIZER_CN}:mailto:{ORGANIZER_EMAIL}"
DEFAULT_OPENAI_MODEL = "gpt-5.5"
DEFAULT_API_TIMEOUT_SECONDS = 120


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


def _parse_ics_person(line: str) -> tuple[str, str] | None:
    cn_match = re.search(r"CN=([^;:]+)", line, re.IGNORECASE)
    email_match = re.search(r":mailto:(.+)$", line, re.IGNORECASE)
    cn = cn_match.group(1).strip().strip('"') if cn_match else ""
    email = email_match.group(1).strip() if email_match else ""
    if not cn and not email:
        return None
    return cn, email


def _attendee_line(cn: str, email: str) -> str:
    if cn:
        return f"ATTENDEE;CN={cn};ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;RSVP=TRUE:mailto:{email}"
    return f"ATTENDEE;ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;RSVP=TRUE:mailto:{email}"


def _force_guy_as_organizer(ics_text: str) -> str:
    raw_lines = ics_text.splitlines()
    logical_lines: list[str] = []
    current = ""
    for raw_line in raw_lines:
        if raw_line.startswith((" ", "\t")):
            current += raw_line[1:]
        else:
            if current:
                logical_lines.append(current)
            current = raw_line
    if current:
        logical_lines.append(current)

    output_lines: list[str] = []
    in_event = False
    event_has_organizer = False
    organizer_people: list[tuple[str, str]] = []
    attendee_emails: set[str] = set()

    for line in logical_lines:
        if line == "BEGIN:VEVENT":
            in_event = True
            event_has_organizer = False
            organizer_people = []
            attendee_emails = set()
            output_lines.append(line)
            continue

        if re.match(r"ORGANIZER[;:]", line, re.IGNORECASE):
            person = _parse_ics_person(line)
            if in_event and person and person[1].lower() != ORGANIZER_EMAIL:
                organizer_people.append(person)
            if in_event and not event_has_organizer:
                output_lines.append(ORGANIZER_LINE)
                event_has_organizer = True
            continue

        if in_event and re.match(r"ATTENDEE[;:]", line, re.IGNORECASE):
            person = _parse_ics_person(line)
            if person and person[1].lower() == ORGANIZER_EMAIL:
                continue
            if person:
                attendee_emails.add(person[1].lower())

        if line == "END:VEVENT" and in_event:
            if not event_has_organizer:
                output_lines.append(ORGANIZER_LINE)
                event_has_organizer = True
            for cn, email in organizer_people:
                if email.lower() not in attendee_emails:
                    output_lines.append(_attendee_line(cn, email))
                    attendee_emails.add(email.lower())
            output_lines.append(line)
            in_event = False
            continue

        output_lines.append(line)

    folded_lines: list[str] = []
    for line in output_lines:
        folded_lines.extend(_fold_ics_line(line))
    return "\r\n".join(folded_lines) + "\r\n"


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

    result: list[str] | None = None

    def on_ok(event=None):
        nonlocal result
        result = [labels[i] for i, k in enumerate(kept) if k]
        root.destroy()

    def on_cancel(event=None):
        nonlocal result
        result = labels
        root.destroy()

    btn = tk.Frame(root)
    btn.pack(pady=8)
    tk.Button(btn, text="OK", width=10, command=on_ok).pack(side=tk.LEFT, padx=5)
    tk.Button(btn, text="Cancel", width=10, command=on_cancel).pack(side=tk.LEFT, padx=5)
    root.bind("<Return>", on_ok)
    root.bind("<Escape>", on_cancel)
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.lift()
    root.focus_force()
    root.update_idletasks()
    root.update()
    if not root.winfo_viewable():
        root.destroy()
        raise RuntimeError("Attendee review dialog was created but is not visible")
    root.mainloop()
    if result is None:
        raise RuntimeError("Attendee review dialog closed without OK or Cancel")
    return result


def _choose_attendees_worker(attendees: list[tuple[str, str]], q: object) -> None:
    try:
        q.put(("ok", _choose_attendees_to_keep(attendees)))
    except Exception:
        q.put(("error", traceback.format_exc()))


def _choose_attendees_safe(attendees: list[tuple[str, str]]) -> list[str]:
    """Run the tkinter dialog in a subprocess so a GUI crash (SIGABRT) can't kill the parent."""
    import multiprocessing as mp

    q: "mp.Queue[tuple[str, object]]" = mp.Queue()
    p = mp.Process(target=_choose_attendees_worker, args=(attendees, q))
    p.start()
    p.join()
    if p.exitcode != 0:
        raise RuntimeError(f"Attendee review dialog exited with code {p.exitcode}")
    if q.empty():
        raise RuntimeError("Attendee review dialog exited without returning a selection")
    status, payload = q.get()
    if status == "error":
        raise RuntimeError(f"Attendee review dialog failed:\n{payload}")
    return payload


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


def _run_text_extractor(
    script_dir: Path,
    script_name: str,
    input_path: Path,
    python_executable: str,
) -> tuple[str, str]:
    script_path = script_dir / "scripts" / script_name
    result = subprocess.run(
        [python_executable, str(script_path), str(input_path)],
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


def _prepare_pdf_text(input_path: Path, script_dir: Path, python_executable: str) -> Path | None:
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
        text, error = _run_text_extractor(script_dir, script_name, input_path, python_executable)
        attempts.append((label, text, _text_quality_score(text), error))

    best_score = max((attempt[2] for attempt in attempts), default=0)
    best_chars = max((len(attempt[1].strip()) for attempt in attempts), default=0)
    if best_score < 1800 or best_chars < 500:
        try:
            result = subprocess.run(
                [
                    python_executable,
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


def _prepare_docx_text(input_path: Path, script_dir: Path, python_executable: str) -> Path | None:
    if input_path.suffix.lower() != ".docx":
        return None

    text_dir = script_dir / "text_versions"
    text_dir.mkdir(exist_ok=True)
    output_path = text_dir / f"{input_path.stem}_extracted.txt"
    text, error = _run_text_extractor(script_dir, "extract_docx_text.py", input_path, python_executable)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    report = [
        f"source_file: {input_path.name}",
        f"timestamp_utc: {timestamp}",
        "selected_method: docx",
        f"selected_score: {_text_quality_score(text)}",
        "attempts:",
        f"- docx: score={_text_quality_score(text)}, chars={len(text.strip())}"
        + (f", error={error}" if error else ""),
        "",
        "selected_text:",
        text.strip(),
        "",
    ]
    output_path.write_text("\n".join(report), encoding="utf-8")
    return output_path


def _prepare_extracted_text(input_path: Path, script_dir: Path, python_executable: str) -> Path | None:
    return (
        _prepare_pdf_text(input_path, script_dir, python_executable)
        or _prepare_docx_text(input_path, script_dir, python_executable)
        or _prepare_image_text(input_path, script_dir)
    )


def _selected_text_from_report(report: str) -> str:
    marker = "\nselected_text:\n"
    if marker not in report:
        return report.strip()
    return report.split(marker, 1)[1].strip()


def _calendar_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "status": {"type": "string", "enum": ["ok", "error"]},
            "error": {"type": "string"},
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "summary": {"type": "string"},
                        "description": {"type": "string"},
                        "location": {"type": "string"},
                        "start_utc": {
                            "type": "string",
                            "description": "UTC start in YYYYMMDDTHHMMSSZ format.",
                        },
                        "end_utc": {
                            "type": "string",
                            "description": "UTC end in YYYYMMDDTHHMMSSZ format.",
                        },
                        "attendees": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "name": {"type": "string"},
                                    "email": {"type": "string"},
                                },
                                "required": ["name", "email"],
                            },
                        },
                    },
                    "required": [
                        "summary",
                        "description",
                        "location",
                        "start_utc",
                        "end_utc",
                        "attendees",
                    ],
                },
            },
        },
        "required": ["status", "error", "events"],
    }


def _read_project_instructions(script_dir: Path) -> str:
    agents_path = script_dir / "AGENTS.md"
    if not agents_path.is_file():
        return ""
    return agents_path.read_text(encoding="utf-8", errors="replace")


def _build_extraction_prompt(
    input_path: Path,
    extracted_text_path: Path | None,
    source_text: str,
    project_instructions: str,
) -> str:
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    source_mtime = datetime.fromtimestamp(input_path.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    text_source = str(extracted_text_path) if extracted_text_path else str(input_path)
    return f"""
Extract future calendar event data from this file and return JSON matching the supplied schema.

Current time: {now_utc} UTC.
Input file: {input_path.name}
Input file modified time: {source_mtime} UTC.
Text source: {text_source}

Rules:
- Return status "error" with a clear error and no events if the file does not contain a future event or if the date/time is ambiguous.
- Compute relative dates from the file/email timestamp when present in the text; otherwise use the input file modified time.
- Unless stated otherwise, assume Jerusalem time for meeting/event times.
- For flights or travel itineraries that state "all times are local", use the local airport/city times and convert each leg to UTC.
- Every event must be in the future relative to Current time.
- Use {ORGANIZER_CN} <{ORGANIZER_EMAIL}> as organizer implicitly; do not include him as an attendee.
- Include all other people, recipients, speakers, hosts, and mailing lists as attendees when an email address is available.
- If a person's email is unknown, omit that attendee rather than inventing an address.
- Keep summaries concise and locations useful.
- Return UTC timestamps exactly as YYYYMMDDTHHMMSSZ.

Project instructions:
{project_instructions}

Extracted text:
{source_text}
""".strip()


def _extract_output_text(response_data: dict) -> str:
    if isinstance(response_data.get("output_text"), str):
        return response_data["output_text"]
    pieces: list[str] = []
    for item in response_data.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and isinstance(content.get("text"), str):
                pieces.append(content["text"])
    return "\n".join(pieces).strip()


def _call_openai_calendar_extractor(
    env: dict,
    prompt: str,
) -> dict:
    api_key = env.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    model = env.get("ICS_OPENAI_MODEL") or env.get("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL
    timeout = int(env.get("ICS_OPENAI_TIMEOUT_SECONDS", DEFAULT_API_TIMEOUT_SECONDS))
    effort = env.get("ICS_OPENAI_REASONING_EFFORT", "low")
    payload: dict = {
        "model": model,
        "input": [{"role": "user", "content": prompt}],
        "reasoning": {"effort": effort},
        "max_output_tokens": int(env.get("ICS_OPENAI_MAX_OUTPUT_TOKENS", "12000")),
        "store": False,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "calendar_events",
                "strict": True,
                "schema": _calendar_schema(),
            },
        },
    }
    if env.get("ICS_ENABLE_WEB_SEARCH", "").lower() in {"1", "true", "yes"}:
        payload["tools"] = [{"type": "web_search_preview", "search_context_size": "medium"}]

    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        "https://api.openai.com/v1/responses",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            response_data = json.loads(resp.read().decode("utf-8"))
    except urlerror.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API returned HTTP {exc.code}: {detail}") from exc
    except urlerror.URLError as exc:
        raise RuntimeError(f"OpenAI API request failed: {exc}") from exc

    status = response_data.get("status")
    if status not in {None, "completed"}:
        raise RuntimeError(
            f"OpenAI API response status was {status}: "
            f"{json.dumps(response_data.get('error') or response_data.get('incomplete_details'))}"
        )
    output_text = _extract_output_text(response_data)
    if not output_text:
        raise RuntimeError("OpenAI API response did not include output text.")
    try:
        return json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"OpenAI API returned non-JSON output: {output_text[:1000]}") from exc


def _parse_utc_stamp(value: str) -> datetime:
    if not re.fullmatch(r"\d{8}T\d{6}Z", value):
        raise ValueError(f"Invalid UTC timestamp: {value}")
    return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def _ics_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(";", "\\;")
        .replace(",", "\\,")
    )


def _fold_ics_line(line: str) -> list[str]:
    encoded_len = 0
    current = ""
    lines: list[str] = []
    limit = 75
    for char in line:
        char_len = len(char.encode("utf-8"))
        if current and encoded_len + char_len > limit:
            lines.append(current)
            current = " " + char
            encoded_len = 1 + char_len
            limit = 75
        else:
            current += char
            encoded_len += char_len
    if current:
        lines.append(current)
    return lines


def _append_ics_line(lines: list[str], line: str) -> None:
    lines.extend(_fold_ics_line(line))


def _build_ics(input_path: Path, extraction: dict) -> str:
    if extraction.get("status") != "ok":
        raise RuntimeError(extraction.get("error") or "Calendar extraction failed.")

    events = extraction.get("events") or []
    if not events:
        raise RuntimeError("Calendar extraction returned no events.")

    now = datetime.now(timezone.utc)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Guy Kindler Watch Folder//ICS Generator//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:REQUEST",
    ]
    dtstamp = now.strftime("%Y%m%dT%H%M%SZ")
    uid_seed = hashlib.sha256(input_path.name.encode("utf-8")).hexdigest()[:12]

    for index, event in enumerate(events, start=1):
        summary = str(event.get("summary") or "").strip()
        if not summary:
            raise RuntimeError(f"Event {index} is missing a summary.")
        start_utc = str(event.get("start_utc") or "")
        end_utc = str(event.get("end_utc") or "")
        start_dt = _parse_utc_stamp(start_utc)
        end_dt = _parse_utc_stamp(end_utc)
        if start_dt <= now:
            raise RuntimeError(f"Event {index} starts in the past: {start_utc}")
        if end_dt <= start_dt:
            raise RuntimeError(f"Event {index} ends before it starts: {end_utc}")

        lines.append("BEGIN:VEVENT")
        _append_ics_line(lines, f"UID:{uid_seed}-{index}-{start_utc}@guy.kindler.mail.huji.ac.il")
        _append_ics_line(lines, f"DTSTAMP:{dtstamp}")
        _append_ics_line(lines, f"DTSTART:{start_utc}")
        _append_ics_line(lines, f"DTEND:{end_utc}")
        _append_ics_line(lines, f"SUMMARY:{_ics_escape(summary)}")
        location = str(event.get("location") or "").strip()
        if location:
            _append_ics_line(lines, f"LOCATION:{_ics_escape(location)}")
        description = str(event.get("description") or "").strip()
        if description:
            _append_ics_line(lines, f"DESCRIPTION:{_ics_escape(description)}")
        _append_ics_line(lines, ORGANIZER_LINE)

        seen_attendees = {ORGANIZER_EMAIL.lower()}
        for attendee in event.get("attendees") or []:
            email = str(attendee.get("email") or "").strip()
            if not email or "@" not in email:
                continue
            email_key = email.lower()
            if email_key in seen_attendees:
                continue
            seen_attendees.add(email_key)
            name = str(attendee.get("name") or "").strip()
            if name:
                line = (
                    f"ATTENDEE;CN={_ics_escape(name)};ROLE=REQ-PARTICIPANT;"
                    f"PARTSTAT=NEEDS-ACTION;RSVP=TRUE:mailto:{email}"
                )
            else:
                line = (
                    "ATTENDEE;ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;"
                    f"RSVP=TRUE:mailto:{email}"
                )
            _append_ics_line(lines, line)
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def _write_failure(
    script_dir: Path,
    input_path: Path,
    output_path: Path,
    command_label: str,
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
        f"command: {command_label}",
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
    extractor_python = env.get("EXTRACTOR_PYTHON", sys.executable)

    output_path = input_path.with_suffix(".ics")
    extracted_text_path = _prepare_extracted_text(input_path, script_dir, extractor_python)
    if extracted_text_path:
        source_report = extracted_text_path.read_text(encoding="utf-8", errors="replace")
        source_text = _selected_text_from_report(source_report)
    else:
        source_text = input_path.read_text(encoding="utf-8", errors="replace")

    try:
        prompt = _build_extraction_prompt(
            input_path,
            extracted_text_path,
            source_text,
            _read_project_instructions(script_dir),
        )
        extraction = _call_openai_calendar_extractor(env, prompt)
        output_path.write_text(_build_ics(input_path, extraction), encoding="utf-8")
    except Exception as exc:
        _write_failure(
            script_dir,
            input_path,
            output_path,
            "openai responses api",
            3,
            stderr=str(exc),
        )
        return 3

    for failure_path in (script_dir / "failure", script_dir / "failure.failure.txt"):
        if failure_path.exists():
            failure_path.unlink()
    print(f"Created {output_path.name}")

    # Let the user review and trim attendees before opening.
    try:
        ics_text = _force_guy_as_organizer(output_path.read_text(encoding="utf-8"))
        output_path.write_text(ics_text, encoding="utf-8")
        attendees = _parse_ics_attendees(ics_text)
        if len(attendees) > 1:
            keep = _choose_attendees_safe(attendees)
        else:
            keep = [a[0] for a in attendees]  # keep all, no dialog
        filtered = _filter_ics_attendees(ics_text, keep, attendees)
        if filtered != ics_text:
            output_path.write_text(filtered, encoding="utf-8")
    except Exception as exc:
        _write_failure(
            script_dir,
            input_path,
            output_path,
            "attendee-review",
            4,
            stderr=str(exc),
        )
        return 4

    try:
        subprocess.run(["open", str(output_path)], check=False)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
