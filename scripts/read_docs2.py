"""Read PDFs that have special characters causing encoding errors."""
import pdfplumber
from pathlib import Path
import sys

# Force UTF-8 output
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

targets = [
    r"C:\Users\Samir\Desktop\RFP\downloads\4 GEM2026B7557307 Open on GeM BidPlus 24-Jun-2026 04-Jul-2026 Annual Maintenance Contract for Networking Devices (Ve.pdf",
    r"C:\Users\Samir\Desktop\RFP\downloads\10 GEM2026B7580746 Open on GeM BidPlus 04-Jun-2026 15-Jun-2026 Hiring of Agency for IT Projects- Milestone basis.pdf",
    r"C:\Users\Samir\Desktop\RFP\downloads\1 AI Application Development NICSIAI Application Development202605 2026_NICSI_282674_1 View  20-Jul-2026 0300 PM\DFB.pdf",
]

for path in targets:
    p = Path(path)
    print(f"\n{'='*70}")
    print(f"FILE: {p.name}")
    print(f"{'='*70}")
    try:
        with pdfplumber.open(path) as pdf:
            print(f"Pages: {len(pdf.pages)}")
            for i, page in enumerate(pdf.pages[:8], 1):
                text = page.extract_text() or ""
                if text.strip():
                    # Replace problematic chars
                    clean = text.encode('ascii', errors='replace').decode('ascii')
                    print(f"\n--- Page {i} ---")
                    print(clean[:3000])
    except Exception as e:
        print(f"Error: {e}")
