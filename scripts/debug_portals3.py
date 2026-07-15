"""Find working public tender listing pages and check their link structure."""
import requests
import warnings
warnings.filterwarnings("ignore")
from bs4 import BeautifulSoup

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})

def check(name, url, verify=True, show_all=False):
    try:
        r = session.get(url, timeout=25, verify=verify)
        soup = BeautifulSoup(r.text, "lxml")
        links = soup.find_all("a", href=True)
        text = soup.get_text(" ", strip=True)
        print(f"\n{'='*60}")
        print(f"{name}  [HTTP {r.status_code}]  links={len(links)}")
        print(f"Page preview: {text[:300]}")
        for a in links[:20]:
            href = a["href"]
            txt  = a.get_text(" ", strip=True)[:80]
            if txt or show_all:
                print(f"  [{txt}]  {href[:120]}")
    except Exception as e:
        print(f"\n{name}: ERROR -> {e}")

# NIC eTenders — the CORRECT public active tenders page
check("NIC eTenders — FrontEndLatestActiveTenders",
      "https://etenders.gov.in/eprocure/app?page=FrontEndLatestActiveTenders&service=page")

# Same for CPPP
check("CPPP — FrontEndLatestActiveTenders",
      "https://eprocure.gov.in/eprocure/app?page=FrontEndLatestActiveTenders&service=page")

# NICSI active tenders
check("NICSI active-tenders",
      "https://www.nicsi.com/nicsi/active-tenders/")

# NICSI GeM bids
check("NICSI GeM bids",
      "https://www.nicsi.com/nicsi/nicsi-gem-bids/")

# MeitY — try a different path
check("MeitY tenders direct",
      "https://www.meity.gov.in/tenders", True)
