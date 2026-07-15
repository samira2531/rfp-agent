"""Inspect HTML context around NICSI download links."""
import requests
import warnings
warnings.filterwarnings("ignore")
from bs4 import BeautifulSoup

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})

for name, url in [
    ("NICSI active-tenders", "https://www.nicsi.com/nicsi/active-tenders/"),
    ("NICSI GeM bids",       "https://www.nicsi.com/nicsi/nicsi-gem-bids/"),
    ("STPI main-tenders",    "https://www.stpi.in/en/main-tenders"),
]:
    print(f"\n{'='*60}\n{name}")
    try:
        r = session.get(url, timeout=30, verify=False)
        soup = BeautifulSoup(r.text, "lxml")
        # Find all links to .zip or .pdf
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not any(href.lower().endswith(ext) for ext in [".zip", ".pdf", ".doc", ".docx"]):
                continue
            # Get parent container text
            parent = a.find_parent(["tr", "li", "div", "article", "section"])
            parent_text = parent.get_text(" ", strip=True)[:300] if parent else ""
            print(f"\n  LINK: {href}")
            print(f"  TEXT: {a.get_text(' ', strip=True)}")
            print(f"  PARENT: {parent_text[:250]}")
            print()
    except Exception as e:
        print(f"  ERROR: {e}")
