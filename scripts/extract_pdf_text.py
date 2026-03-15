#!/usr/bin/env python3
"""
Best-effort text extraction from a PDF without external dependencies.

Usage:
  python3 extract_pdf_text.py /path/to/file.pdf
  python3 extract_pdf_text.py /path/to/file.pdf -o /path/to/output.txt

How it works:
- Scans the PDF for compressed streams, tries Flate (zlib) decompression,
  and extracts text operands from Tj/TJ operators.
- This is a heuristic extractor and works best for text-based PDFs.
- For scanned/image-only PDFs, this will likely return little or no text.
"""

import argparse
import re
import sys
import zlib
from pathlib import Path


def _iter_streams(pdf_bytes: bytes):
    for m in re.finditer(br"stream\r?\n", pdf_bytes):
        start = m.end()
        end = pdf_bytes.find(b"endstream", start)
        if end == -1:
            continue
        yield pdf_bytes[start:end]


def _try_decompress(stream: bytes):
    # Try standard zlib first, then raw deflate
    try:
        return zlib.decompress(stream)
    except Exception:
        try:
            return zlib.decompress(stream, -15)
        except Exception:
            return None


def extract_pdf_text(path: Path) -> str:
    raw = path.read_bytes()
    texts = []

    for stream in _iter_streams(raw):
        data = _try_decompress(stream)
        if data is None:
            continue

        # Extract literal strings before Tj
        for m in re.finditer(rb"\((?:\\.|[^\\)])*\)\s*Tj", data):
            t = m.group(0)
            t = re.sub(rb"\s*Tj$", b"", t)
            t = t[1:-1]
            try:
                texts.append(t.decode("latin1"))
            except Exception:
                pass

        # Extract strings inside TJ arrays
        for m in re.finditer(rb"\[(.*?)\]\s*TJ", data, re.S):
            arr = m.group(1)
            for sm in re.finditer(rb"\((?:\\.|[^\\)])*\)", arr):
                t = sm.group(0)[1:-1]
                try:
                    texts.append(t.decode("latin1"))
                except Exception:
                    pass

    # Unescape common sequences
    text = "\n".join(texts)
    text = (
        text.replace("\\n", "\n")
        .replace("\\r", "\r")
        .replace("\\t", "\t")
        .replace("\\(", "(")
        .replace("\\)", ")")
        .replace("\\\\", "\\")
    )
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract text from a PDF (best-effort)")
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
