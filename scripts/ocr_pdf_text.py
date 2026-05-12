#!/usr/bin/env python3
"""
OCR a scanned PDF into a text file using PyMuPDF (fitz) + tesseract.

Usage:
  python3 scripts/ocr_pdf_text.py path/to/file.pdf -o /tmp/out.txt

Notes:
  - Use this only when `scripts/extract_pdf_text.py` produces unreadable output
    (e.g., scanned/image-only PDFs).
  - Requires `tesseract` on PATH and the Python package `fitz` (PyMuPDF).
  - Defaults to Hebrew+English OCR when Hebrew data is installed, otherwise English.
  - Output is written in a simple page-by-page format with page markers.
"""
import argparse
import os
import shutil
import subprocess
import tempfile

import fitz  # PyMuPDF


def _available_tesseract_langs(tesseract_bin: str) -> set[str]:
    try:
        result = subprocess.run(
            [tesseract_bin, "--list-langs"],
            text=True,
            capture_output=True,
            check=True,
        )
    except Exception:
        return set()
    return {
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() and not line.startswith("List of available languages")
    }


def _resolve_lang(requested: str, tesseract_bin: str) -> str:
    langs = _available_tesseract_langs(tesseract_bin)
    requested_parts = [part for part in requested.split("+") if part]
    available_parts = [part for part in requested_parts if part in langs]
    if available_parts:
        return "+".join(available_parts)
    return "eng" if "eng" in langs else requested


def ocr_pdf_to_text(pdf_path: str, out_path: str, dpi: int = 300, lang: str = "heb+eng") -> None:
    tesseract_bin = shutil.which("tesseract") or "/opt/homebrew/bin/tesseract"
    lang = _resolve_lang(lang, tesseract_bin)
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    doc = fitz.open(pdf_path)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as out, tempfile.TemporaryDirectory() as tmpdir:
        out.write(f"[OCR source: {os.path.basename(pdf_path)}]\n\n")
        for i, page in enumerate(doc, start=1):
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            img_path = os.path.join(tmpdir, f"page_{i}.png")
            pix.save(img_path)

            txt_base = os.path.join(tmpdir, f"page_{i}")
            subprocess.run([tesseract_bin, img_path, txt_base, "-l", lang], check=True)

            with open(txt_base + ".txt", "r", encoding="utf-8", errors="ignore") as f:
                out.write(f"[Page {i}]\n")
                out.write(f.read().strip())
                out.write("\n\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="OCR a scanned PDF to text using PyMuPDF + tesseract")
    parser.add_argument("pdf", help="Path to input PDF")
    parser.add_argument("-o", "--output", required=True, help="Path to output text file")
    parser.add_argument("--dpi", type=int, default=300, help="Render DPI (default: 300)")
    parser.add_argument("--lang", default="heb+eng", help="Tesseract language (default: heb+eng)")
    args = parser.parse_args()

    ocr_pdf_to_text(args.pdf, args.output, dpi=args.dpi, lang=args.lang)


if __name__ == "__main__":
    main()
