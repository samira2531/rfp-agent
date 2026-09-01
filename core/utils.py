"""
Shared constants, path definitions, and helper functions used across all modules.
"""

import re
import csv
import yaml
import urllib.parse
import requests
from pathlib import Path
from datetime import datetime

# ── Project root (two levels up from this file: core/utils.py → core/ → RFP/)
ROOT_DIR = Path(__file__).parent.parent

CONFIG_FILE  = ROOT_DIR / "config" / "config.yaml"
DOWNLOADS_DIR = ROOT_DIR / "downloads"
DATA_DIR     = ROOT_DIR / "data"
LOGS_DIR     = ROOT_DIR / "logs"
SEEN_FILE    = DATA_DIR / "seen_urls.txt"

DOC_EXTENSIONS = {".pdf", ".doc", ".docx", ".zip", ".xlsx", ".xls"}


def load_config() -> dict:
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_seen() -> set:
    DATA_DIR.mkdir(exist_ok=True)
    if SEEN_FILE.exists():
        return set(SEEN_FILE.read_text(encoding="utf-8").splitlines())
    return set()


def save_seen(seen: set):
    SEEN_FILE.write_text("\n".join(sorted(seen)), encoding="utf-8")


def matches_keywords(text: str, keywords: list) -> bool:
    """True if keywords list is empty (grab all), or any keyword found in text."""
    if not keywords:
        return True
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in keywords)


def matched_kw_string(text: str, keywords: list) -> str:
    if not keywords:
        return ""
    return ", ".join(kw for kw in keywords if kw.lower() in text.lower())


def is_startup_eligible(text: str, startup_keywords: list) -> bool:
    """Return True if the RFP page text indicates startup eligibility."""
    if not startup_keywords:
        return True     # no filter configured — allow all
    return matches_keywords(text, startup_keywords)


# Terms that clearly indicate a NON-India tender
_NON_INDIA = [
    "USA (", "U.S.A", "United States", "UK (", "United Kingdom",
    "Canada (", "Australia (", "South Africa", "Germany",
    "France", "Netherlands", "Singapore", "China", "Japan",
    "US-FED-", " US ", "(US)", "Federal Register",
]

# Short abbreviations that must be matched as whole words (not as substrings
# of longer English words, e.g. "GeM" inside "management", "NIC" inside "electronic")
_INDIA_ABBR = {"NIC", "GeM", "CPPP", "STPI", "GOI", "GoI", "MeitY", "NICSI"}


def is_india_tender(text: str, location_filter: dict) -> bool:
    """
    Returns True if the tender appears to be India-based.
    location_filter keys: enabled (bool), include (list), exclude (list)
    """
    if not location_filter.get("enabled", False):
        return True

    text_lower = text.lower()

    # Explicit exclude check (fast path for non-India tenders)
    for term in location_filter.get("exclude", _NON_INDIA):
        if term.lower() in text_lower:
            return False

    include = location_filter.get("include", [])
    if not include:
        return True     # no include list → allow if not excluded

    for term in include:
        if term in _INDIA_ABBR:
            # Word-boundary match to prevent "GeM" matching "management",
            # "NIC" matching "electronic", "technical", etc.
            if re.search(r'\b' + re.escape(term) + r'\b', text, re.IGNORECASE):
                return True
        else:
            if term.lower() in text_lower:
                return True

    return False


def read_page_text(url: str, session, log) -> str:
    """Fetch a URL and return its full visible text. Returns '' on error."""
    from bs4 import BeautifulSoup
    try:
        r = session.get(url, timeout=30)
        r.raise_for_status()
        return BeautifulSoup(r.text, "lxml").get_text(" ", strip=True)
    except Exception as e:
        log.warning(f"  Could not read page [{url}]: {e}")
        return ""


def unique_path(dest: Path) -> Path:
    """Avoid overwriting: append _1, _2, … if file already exists."""
    if not dest.exists():
        return dest
    stem, suffix = dest.stem, dest.suffix
    i = 1
    while True:
        candidate = dest.parent / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def safe_filename(name: str, fallback: str = "document") -> str:
    name = re.sub(r"[^\w\s.()\-]", "", name).strip()
    return (name[:120] or fallback)


def download_file(url: str, dest: Path, session: requests.Session,
                  max_mb: int, log, ssl_verify: bool = True):
    """Download url to dest (auto-renamed if exists). Returns actual saved Path or None."""
    try:
        with session.get(url, stream=True, timeout=40, verify=ssl_verify) as r:
            r.raise_for_status()
            size = int(r.headers.get("content-length", 0))
            if size and size > max_mb * 1024 * 1024:
                log.warning(f"Skipping — too large ({size // 1024 // 1024} MB): {url}")
                return None
            dest = unique_path(dest)
            with open(dest, "wb") as f:
                downloaded = 0
                for chunk in r.iter_content(chunk_size=65536):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if downloaded > max_mb * 1024 * 1024:
                        log.warning(f"Aborted — exceeded size limit: {url}")
                        try: dest.unlink()
                        except Exception: pass
                        return None
            log.info(f"  Saved: {dest.name}")
            return dest
    except Exception as e:
        log.error(f"  Download failed [{url}]: {e}")
        return None


_DEADLINE_LABEL_RE = re.compile(
    r'(?:bid\s+end\s+date|last\s+date|closing\s+date|due\s+date|'
    r'submission\s+deadline|bid\s+closing|bid\s+due|tender\s+closing|'
    r'deadline\s+for\s+(?:bid|submission|tender)|date\s+of\s+closing|'
    r'end\s+date\s+for\s+submission|close\s+date|'
    r'closing\s+time|end\s+date/time|bid\s+end)',
    re.IGNORECASE,
)
_MONTH_MAP = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
}


def extract_deadline(text: str) -> str:
    """Return first tender submission deadline found in text as 'YYYY-MM-DD', or ''."""
    for m in _DEADLINE_LABEL_RE.finditer(text):
        window = text[m.start(): m.start() + 300]
        # DD-MM-YYYY (optionally followed by time HH:MM:SS)
        dm = re.search(r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})', window)
        if dm:
            d, mo, y = int(dm.group(1)), int(dm.group(2)), int(dm.group(3))
            # Prefer interpretation where d<=31 and mo<=12; swap if needed
            if d > 12 and mo <= 12 and 1 <= d <= 31 and 2020 <= y <= 2035:
                return f"{y:04d}-{mo:02d}-{d:02d}"
            if 1 <= d <= 31 and 1 <= mo <= 12 and 2020 <= y <= 2035:
                return f"{y:04d}-{mo:02d}-{d:02d}"
        # DD MonthName YYYY
        dm = re.search(
            r'(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s,]+(\d{4})',
            window, re.IGNORECASE,
        )
        if dm:
            d, mo_str, y = int(dm.group(1)), dm.group(2).lower()[:3], int(dm.group(3))
            mo = _MONTH_MAP.get(mo_str, 0)
            if mo and 2020 <= y <= 2035:
                return f"{y:04d}-{mo:02d}-{d:02d}"
    return ""


def extract_deadline_from_pdf(path: Path) -> str:
    """Read up to 6 pages of a PDF and extract the submission deadline. Returns '' on failure."""
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages[:6])
        return extract_deadline(text)
    except Exception:
        return ""


def is_deadline_past(deadline_iso: str) -> bool:
    """Return True if a non-empty ISO deadline string is in the past (before today)."""
    if not deadline_iso:
        return False
    return deadline_iso < datetime.now().strftime("%Y-%m-%d")


def record_csv(row: dict):
    csv_path = ROOT_DIR / load_config()["output"]["csv_file"]
    csv_path.parent.mkdir(exist_ok=True)
    write_header = not csv_path.exists()
    fields = ["date", "title", "source", "url", "file", "keywords_matched", "deadline"]
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if write_header:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in fields})


def extract_doc_links(text: str, extensions: set) -> list:
    links = re.findall(r'https?://[^\s"\'<>]+', text)
    return [l for l in links if Path(urllib.parse.urlparse(l).path).suffix.lower() in extensions]


# URL path segments that indicate an individual RFP/bid detail page
_DETAIL_RE = re.compile(
    r'/(bid|rfp|solicitation|opportunity|contract|tender|procurement|notice|award|event)s?'
    r'[/_\-]',
    re.IGNORECASE,
)

# Query-string patterns used by NIC eProcure / Indian govt portals
_DETAIL_QS = re.compile(
    r'(TenderDetails|TenderDetail|BidDetail|BidView|BidId|bidId|bid_id|tender_id'
    r'|tenderid|notice_id|noticeId|BidType=TENDER|bidNumber)',
    re.IGNORECASE,
)


# Domains that are never RFP detail pages
_NON_PROCUREMENT_DOMAINS = {
    "wa.me", "t.me", "telegram.me", "twitter.com", "x.com",
    "facebook.com", "linkedin.com", "instagram.com", "youtube.com",
    "whatsapp.com", "mailto:", "tel:",
}


def is_detail_page(url: str, extra_patterns: list = None) -> bool:
    """True if a URL looks like an individual RFP/bid detail page."""
    parsed = urllib.parse.urlparse(url)
    hostname = parsed.hostname or ""
    path  = parsed.path
    query = parsed.query

    # Exclude social/messaging domains
    if any(d in hostname for d in _NON_PROCUREMENT_DOMAINS):
        return False

    # Standard path patterns
    if _DETAIL_RE.search(path):
        return True
    # Long numeric ID in path — only valid for known procurement hostnames
    if re.search(r'/\d{5,}', path):
        procurement_hint = any(k in hostname for k in (
            "gem", "eprocure", "etenders", "nicgep", "tender",
            "bidplus", "procure", "eproc", "nicsi", "sppp",
        ))
        if procurement_hint:
            return True
    # NIC eProcure and similar query-string patterns
    if _DETAIL_QS.search(query):
        return True
    # Site-specific custom patterns from config
    if extra_patterns:
        if any(re.search(p, url, re.IGNORECASE) for p in extra_patterns):
            return True
    return False


def follow_and_download(page_url: str, session, max_mb: int,
                        extensions: set, log, ssl_verify: bool = True) -> tuple:
    """
    Visit an RFP detail page (HTML) and download every attached document.
    Returns (saved_file_paths: list, deadline: str).
    """
    from bs4 import BeautifulSoup
    saved, deadline = [], ""
    try:
        r = session.get(page_url, timeout=30, verify=ssl_verify)
        r.raise_for_status()

        content_type = r.headers.get("content-type", "").lower()

        # If the URL itself IS a document, save it directly
        if "html" not in content_type:
            ext = Path(urllib.parse.urlparse(page_url).path).suffix.lower()
            if ext in extensions and r.content:
                fname  = safe_filename(Path(urllib.parse.urlparse(page_url).path).stem) + ext
                dest   = unique_path(DOWNLOADS_DIR / fname)
                dest.write_bytes(r.content)
                log.info(f"  Saved: {dest.name}")
                saved.append(str(dest))
            return saved, deadline

        # Parse the HTML page — extract deadline from page text first
        soup = BeautifulSoup(r.text, "lxml")
        page_text = soup.get_text(" ", strip=True)
        deadline  = extract_deadline(page_text)

        for a in soup.find_all("a", href=True):
            href    = a["href"].strip()
            abs_url = urllib.parse.urljoin(page_url, href)
            ext     = Path(urllib.parse.urlparse(abs_url).path).suffix.lower()
            if ext not in extensions:
                continue
            link_text = a.get_text(" ", strip=True)
            fname = safe_filename(link_text or Path(urllib.parse.urlparse(abs_url).path).stem) + ext
            dest  = DOWNLOADS_DIR / fname
            actual = download_file(abs_url, dest, session, max_mb, log, ssl_verify=ssl_verify)
            if actual:
                saved.append(str(actual))

    except Exception as e:
        log.error(f"  follow_and_download error [{page_url}]: {e}")

    return saved, deadline
