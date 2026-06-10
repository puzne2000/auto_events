# Repository Guidelines

## Purpose
This project generates ics calendar files for meetings, based on files which are put in this folder.

## Formats
The expected format of files are pdf, text, docx, or picture files.

## Image Files
- If the input is an image file (`.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`, `.heic`, `.tiff`, `.bmp`), use your vision capabilities to read it directly and extract the event/meeting details.
- If the image is unclear or vision fails, fall back to tesseract OCR (installed at `/opt/homebrew/bin/tesseract`):
  `tesseract path/to/image.png /tmp/out_text && cat /tmp/out_text.txt`
- Verify the extracted text is coherent before proceeding to generate the `.ics` file.

## Project Structure
- Top level: files that describe events, or email exchanges where events or meetings are discussed.

- `scripts/`: Some Python scripts that can be used to extract text from various file types. The scripts contain documentation about how they can be used, but here are some examples:
- `scripts/extract_docx_text.py path/to/file.docx -o /tmp/out.txt`  
  Extracts plain text from a DOCX file.
- `scripts/extract_pdf_text.py path/to/file.pdf -o /tmp/out.txt`  
  Best-effort PDF text extraction (works for text-based PDFs).
- `scripts/extract_pdf_text_fitz.py path/to/file.pdf -o /tmp/out.txt`  
  PDF text extraction using PyMuPDF (cleaner output for many text-based PDFs).
- `scripts/ocr_pdf_text.py` useful only if the PDF is scanned/image-only.

How to verify extraction worked:
- Open the output text and confirm words are readable (not scattered characters or symbols) and that text is coherent.
- If the output is mostly garbage or very short relative to the PDF length, treat it as a failed extraction and try the next method.

If OCR is needed, use `scripts/ocr_pdf_text.py` (PyMuPDF + tesseract) and save outputs as `text_versions/*_ocr.txt` (one per letter).
Example:
`python3 scripts/ocr_pdf_text.py path/to/file.pdf -o text_versions/file_ocr.txt`


## Data Sensitivity & Handling
These files contain personal and academic records. Avoid copying sensitive data outside this folder and prefer local processing (`scripts/`) over external services.

## Preparation
- You may need to read word (DOCX) files. Create a virtual environment and install necessary packages when you need them
- Read the text of given file and understand it, use text extraction scripts as needed and verify that the text is not garbled (or else try another method)  
- My name is Guy Kindler, and my email for calendar event creation is [guy.kindler@mail.huji.ac.il]
- use unix or python to find out the current date and time, and use it to reference the times mentioned in the email or file. 

## Generating the ics files
- If the input file is an email exchange, add all recepients to the event
Use the following points in creating the file:
- Always set the organizer to Guy Kindler using `guy.kindler@mail.huji.ac.il`; every other person, mailing list, speaker, sender, or host should be an attendee, not the organizer.
- Unless stated otherwise, assume Jerusalem time
- If the event is a meeting, add the location to the event if you can find it
- use web search or any other means to find anything you need to get the best details possible about the event, including location
- Look at the time stamps of the emails or documents you are presented with. Remember that relative times like "tomorrow" should be computed with respect to the time of creation of the email or document, not with respect to the current time.
- after figuring out the time of the event, make sure that it is in the future compared to the current time, otherwise something must be wrong with the file or your understanding of it: in that case fail and report an error
