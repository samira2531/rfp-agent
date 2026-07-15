"""Check NICSI and other CAPTCHA-free India tender sources."""
import requests
import warnings
warnings.filterwarnings("ignore")
from bs4 import BeautifulSoup
from pathlib import Path

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
})

def check_full(name, url, verify=True):
    try:
        r = session.get(url, timeout=30, verify=verify)
        soup = BeautifulSoup(r.text, "lxml")
        links = soup.find_all("a", href=True)
        print(f"\n{'='*60}")
        print(f"{name}  [HTTP {r.status_code}]  links={len(links)}")
        # Show all links
        for a in links:
            href = a["href"]
            txt  = a.get_text(" ", strip=True)[:80]
            ext  = Path(href.split("?")[0]).suffix.lower()
            # highlight doc and tender links
            if ext in (".pdf", ".doc", ".docx", ".zip"):
                print(f"  DOC [{txt}]  ->  {href[:150]}")
            elif any(k in href.lower() for k in ["tender", "bid", "rfp", "procure", "notice", "circular"]):
                print(f"  TENDER [{txt}]  ->  {href[:150]}")
    except Exception as e:
        print(f"\n{name}: ERROR -> {e}")

check_full("NICSI active-tenders",  "https://www.nicsi.com/nicsi/active-tenders/")
check_full("NICSI GeM bids",        "https://www.nicsi.com/nicsi/nicsi-gem-bids/")
check_full("STPI tenders",          "https://www.stpi.in/tenders", verify=False)
check_full("NIC home tenders link", "https://www.nic.in/tenders/")

# Try India-specific aggregators with free access
check_full("WorksBeauty India Tenders RSS", "https://www.worksbeauty.com/tenders.rss")

# CPPP xml export (if exists)
try:
    r = session.get("https://eprocure.gov.in/cppp/activetenders", timeout=20)
    print(f"\nCPPP activetenders HTTP {r.status_code}, len={len(r.text)}")
    print(r.text[:500])
except Exception as e:
    print(f"\nCPPP xml: ERROR {e}")
