"""Deep-dive into NIC eProcure HTML structure to find tender links."""
import requests
import warnings
warnings.filterwarnings("ignore")
from bs4 import BeautifulSoup

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
})

# Step 1: visit home page to get session cookie
r0 = session.get("https://etenders.gov.in/eprocure/app", timeout=25)
print(f"Home page: HTTP {r0.status_code}, cookies: {dict(session.cookies)}")

# Step 2: visit active tenders page with session
r = session.get(
    "https://etenders.gov.in/eprocure/app?page=FrontEndLatestActiveTenders&service=page",
    timeout=25
)
print(f"Tenders page: HTTP {r.status_code}, content-length={len(r.text)}")

soup = BeautifulSoup(r.text, "lxml")

# Print ALL links with their text
print("\n--- All links on tenders page ---")
for a in soup.find_all("a", href=True):
    href = a["href"]
    txt  = a.get_text(" ", strip=True)[:80]
    print(f"  [{txt}]  ->  {href[:120]}")

# Print any tables
print(f"\n--- Tables on page: {len(soup.find_all('table'))} ---")
for t in soup.find_all("table"):
    rows = t.find_all("tr")
    print(f"  Table rows: {len(rows)}")
    for row in rows[:3]:
        print(f"  Row: {row.get_text(' ', strip=True)[:120]}")

# Print full page text
print("\n--- Page text (first 2000 chars) ---")
print(soup.get_text(" ", strip=True)[:2000])
