"""Simulate exactly what the scraper does for NICSI GeM Bids page."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import urllib.parse
from pathlib import Path
import requests
import warnings
warnings.filterwarnings("ignore")
from bs4 import BeautifulSoup

from core.utils import matches_keywords, load_config, is_detail_page

config = load_config()
keywords = config.get("keywords", [])
print("Keywords:", keywords)

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})

url = "https://www.nicsi.com/nicsi/nicsi-gem-bids/"
print(f"\nFetching: {url}")
r = session.get(url, timeout=30)
soup = BeautifulSoup(r.text, "lxml")

DOC_EXTENSIONS = {".pdf", ".doc", ".docx", ".zip", ".xlsx", ".xls"}

print(f"\n--- Processing all <a> tags ---")
found = 0
for a in soup.find_all("a", href=True):
    href    = a["href"].strip()
    abs_url = urllib.parse.urljoin(url, href)
    parsed  = urllib.parse.urlparse(abs_url)
    ext     = Path(parsed.path).suffix.lower()

    if parsed.scheme not in ("http", "https"):
        continue

    link_text = a.get_text(" ", strip=True)
    context   = f"{link_text} {a.get('title') or ''}"
    parent    = a.find_parent(["td", "tr", "li", "div", "p", "article"])
    if parent:
        context += " " + parent.get_text(" ", strip=True)[:400]

    kw_match = matches_keywords(context, keywords)

    if ext in DOC_EXTENSIONS:
        print(f"\n  DOC LINK: {abs_url}")
        print(f"  ext={ext!r}, kw_match={kw_match}")
        print(f"  link_text={link_text!r}")
        print(f"  context (first 200): {context[:200]!r}")
        if not kw_match:
            # Show which keyword would have matched
            lc = context.lower()
            near = [(kw, kw.lower() in lc) for kw in keywords]
            print(f"  No keyword match. Closest:")
            for kw, m in near:
                if m:
                    print(f"    MATCH: {kw!r}")
        found += 1

print(f"\nTotal doc links found and checked: {found}")
