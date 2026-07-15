"""Find the right public-access URLs for NIC eProcure and other portals."""
import requests
import warnings
warnings.filterwarnings("ignore")
from bs4 import BeautifulSoup

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})

def check(name, url, verify=True):
    try:
        r = session.get(url, timeout=25, verify=verify)
        soup = BeautifulSoup(r.text, "lxml")
        text = soup.get_text(" ", strip=True)[:300]
        links = [a["href"] for a in soup.find_all("a", href=True)]
        # find tender-like links
        tender_links = [l for l in links if any(
            k in l.lower() for k in ["tender", "bid", "rfp", "procure", "notice"]
        )]
        print(f"\n{'='*60}")
        print(f"{name}  [{r.status_code}]")
        print(f"URL: {url}")
        print(f"Total links: {len(links)}, tender-like: {len(tender_links)}")
        print(f"Page text: {text[:200]}")
        for l in tender_links[:8]:
            print(f"  -> {l[:120]}")
    except Exception as e:
        print(f"\n{name}: ERROR -> {e}")

# NIC eProcure public search (FrontEndLatestActiveTenderWise does not need session)
check("CPPP — public active tenders",
      "https://eprocure.gov.in/eprocure/app?page=FrontEndLatestActiveTenderWise&service=page")
check("NIC eTenders — public active",
      "https://etenders.gov.in/eprocure/app?page=FrontEndLatestActiveTenderWise&service=page")
check("NIC eTenders — home",
      "https://etenders.gov.in/eprocure/app")
check("Maharashtra — public active",
      "https://mahatenders.gov.in/nicgep/app?page=FrontEndLatestActiveTenderWise&service=page")
check("Delhi — public active",
      "https://govtprocurement.delhi.gov.in/nicgep/app?page=FrontEndLatestActiveTenderWise&service=page")

# NICSI deeper look
check("NICSI tenders page",
      "https://www.nicsi.com/nicsi/tenders")

# STPI look for PDF links
check("STPI tenders",
      "https://www.stpi.in/en/tenders", True)

# TenderTiger India
check("TenderTiger IT India (free)",
      "https://www.tendertiger.com/search.php?searchcat=it-services&country=India")
