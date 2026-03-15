#!/usr/bin/env python3
"""
Extract text from a PDF using PyMuPDF (fitz).

Usage:
  python3 extract_pdf_text_fitz.py /path/to/file.pdf
  python3 extract_pdf_text_fitz.py /path/to/file.pdf -o /path/to/output.txt

Notes:
- This uses PyMuPDF (fitz). If it's not installed, install via:
    python3 -m pip install --user pymupdf
- Works well for text-based PDFs. Scanned/image PDFs will need OCR.
"""

import argparse
import sys
from pathlib import Path


def extract_pdf_text(path: Path) -> str:
    try:
        import fitz  # PyMuPDF
    except Exception as e:
        raise RuntimeError(
            "PyMuPDF (fitz) not installed. Install with: python3 -m pip install --user pymupdf"
        ) from e

    doc = fitz.open(path)
    try:
        return "\n".join(page.get_text("text") for page in doc)
    finally:
        doc.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract text from a PDF using PyMuPDF")
    parser.add_argument("pdf", type=Path, help="Path to .pdf file")
    parser.add_argument("-o", "--output", type=Path, help="Write output to file instead of stdout")
    args = parser.parse_args()

    if not args.pdf.exists():
        print(f"error: file not found: {args.pdf}", file=sys.stderr)
        return 2

    text = extract_pdf_text(args.pdf)

    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
