"""
Probe each configured website and the GeM API to find which ones
return PDF links — run this before the full agent to verify sources.
"""
import sys, requests, warnings
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent.parent))
warnings.filterwarnings("ignore")

from core.utils import load_config

cfg  = load_config()
UA   = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/125.0 Safari/537.36")

sess = requests.Session()
sess.headers["User-Agent"] = UA

print("=" * 65)
print("PORTAL PROBE RESULTS")
print("=" * 65)

for site in cfg.get("websites", []):
    name = site["name"]
    url  = site["url"]
    verify = site.get("ssl_verify", True)
    try:
        r = sess.get(url, timeout=20, verify=verify)
        soup = BeautifulSoup(r.text, "lxml")
        all_links = soup.find_all("a", href=True)
        pdf_links = [a["href"] for a in all_links
                     if any(a["href"].lower().endswith(e)
                            for e in (".pdf", ".zip", ".docx", ".doc"))]
        print(f"\n{'OK' if r.ok else 'ERR':4}  {name}")
        print(f"      HTTP {r.status_code}  |  {len(all_links)} links  |  {len(pdf_links)} doc links")
        for lnk in pdf_links[:5]:
            print(f"        {lnk[:90]}")
    except Exception as e:
        print(f"\nFAIL  {name}")
        print(f"      {e}")

# GeM probe
print("\n" + "=" * 65)
print("GEM BIDPLUS PROBE")
print("=" * 65)
for term in ["IT services", "managed services"]:
    try:
        r = sess.get(
            "https://bidplus.gem.gov.in/bidlists",
            params={"bid_status": "1", "page_no": "1",
                    "search_bid_file": term},
            headers={"Accept": "application/json, text/javascript, */*; q=0.01",
                     "X-Requested-With": "XMLHttpRequest",
                     "Referer": "https://bidplus.gem.gov.in/all-bids"},
            timeout=20,
        )
        ct = r.headers.get("content-type", "")
        print(f"\nGET /bidlists?search={term!r}")
        print(f"  Status: {r.status_code}  Content-Type: {ct[:60]}")
        print(f"  Body preview: {r.text[:300]}")
    except Exception as e:
        print(f"\nGET /bidlists '{term}': {e}")
