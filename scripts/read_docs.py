"""Extract and print text from all downloaded RFP PDFs."""
import glob
import pdfplumber
from pathlib import Path

downloads = Path(r"C:\Users\Samir\Desktop\RFP\downloads")

# Collect all PDFs (including those inside extracted ZIP folders)
pdfs = list(downloads.glob("*.pdf")) + list(downloads.glob("**/*.pdf"))
pdfs = sorted(set(pdfs))

for pdf_path in pdfs:
    print(f"\n{'='*70}")
    print(f"FILE: {pdf_path.name}")
    print(f"PATH: {pdf_path}")
    print(f"{'='*70}")
    try:
        with pdfplumber.open(pdf_path) as pdf:
            total_pages = len(pdf.pages)
            print(f"Pages: {total_pages}\n")
            # Read up to first 6 pages for overview
            for i, page in enumerate(pdf.pages[:6], 1):
                text = page.extract_text() or ""
                if text.strip():
                    print(f"--- Page {i} ---")
                    print(text.strip()[:3000])
                    print()
    except Exception as e:
        print(f"Error reading PDF: {e}")
