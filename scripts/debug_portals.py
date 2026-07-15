"""Debug script: check what links India portals expose publicly."""
import requests
import warnings
warnings.filterwarnings("ignore")
from bs4 import BeautifulSoup

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})

portals = [
    ("NIC eTenders", "https://etenders.gov.in/eprocure/app?page=FrontEndTendersByOrganisationPublic&service=page", True),
    ("Maharashtra",  "https://mahatenders.gov.in/nicgep/app?page=FrontEndTendersByOrganisationPublic&service=page", True),
    ("Delhi",        "https://govtprocurement.delhi.gov.in/nicgep/app?page=FrontEndTendersByOrganisationPublic&service=page", True),
    ("MeitY",        "https://www.meity.gov.in/tenders", True),
    ("NICSI",        "https://www.nicsi.com/nicsi/tenders", True),
    ("Rajasthan",    "https://sppp.rajasthan.gov.in/sppp/Home/index", False),
    ("STPI",         "https://www.stpi.in/tenders", False),
]

for name, url, verify in portals:
    try:
        r = session.get(url, timeout=20, verify=verify)
        soup = BeautifulSoup(r.text, "lxml")
        links = soup.find_all("a", href=True)
        content_links = [
            a for a in links
            if len(a.get_text().strip()) > 5
            and "javascript" not in a["href"].lower()
            and "#" != a["href"].strip()
        ]
        print(f"\n{'='*60}")
        print(f"{name}: HTTP {r.status_code}, links={len(links)}, content_links={len(content_links)}")
        print(f"URL: {url}")
        for a in content_links[:8]:
            href = a["href"]
            text = a.get_text(" ", strip=True)[:80]
            print(f"  [{text}]  ->  {href[:120]}")
    except Exception as e:
        print(f"\n{name}: ERROR -> {e}")
