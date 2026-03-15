#!/usr/bin/env python3
"""
Extract plain text from a .docx file.

Usage:
  python3 extract_docx_text.py /path/to/file.docx
  python3 extract_docx_text.py /path/to/file.docx -o /path/to/output.txt

Notes:
- Output is a simple paragraph-per-line text dump.
- The script is self-contained and requires only Python 3.
"""

import argparse
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path


def extract_docx_text(path: Path) -> str:
    with zipfile.ZipFile(path, "r") as z:
        xml = z.read("word/document.xml")

    root = ET.fromstring(xml)
    paragraphs = []
    for para in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
        runs = []
        for t in para.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"):
            runs.append(t.text or "")
        if runs:
            paragraphs.append("".join(runs))
    return "\n".join(paragraphs)


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract text from a .docx file")
    parser.add_argument("docx", type=Path, help="Path to .docx file")
    parser.add_argument("-o", "--output", type=Path, help="Write output to file instead of stdout")
    args = parser.parse_args()

    if not args.docx.exists():
        print(f"error: file not found: {args.docx}", file=sys.stderr)
        return 2

    text = extract_docx_text(args.docx)

    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
