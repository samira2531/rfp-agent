"""
TED Europa (Tenders Electronic Daily) — EU official procurement journal.
Tries the v3 JSON API first; falls back to scraping the public search page.
~800,000 notices/year, no login required.
"""

import urllib.parse
from datetime import datetime

from bs4 import BeautifulSoup

from core.utils import (
    matches_keywords, matched_kw_string,
    follow_and_download, record_csv,
    DOC_EXTENSIONS,
)

_API_URL  = "https://api.ted.europa.eu/v3/notices/search"
_WEB_URL  = "https://ted.europa.eu/en/search/result"


def fetch_ted(config: dict, seen: set, new_items: list, session, log):
    cfg = config.get("ted", {})
    if not cfg.get("enabled", False):
        return

    search_terms = cfg.get("search_terms") or config.get("keywords") or ["managed services"]
    max_mb       = config.get("downloads", {}).get("max_file_size_mb", 100)
    extensions   = {e.lower() for e in config.get("downloads", {}).get(
        "document_extensions", list(DOC_EXTENSIONS))}
    keywords     = config.get("keywords", [])

    # Deduplicate: run at most 3 unique terms to avoid hammering
    for term in list(dict.fromkeys(search_terms))[:3]:
        log.info(f"[TED] Searching: '{term}'")
        try:
            found = _try_api(term, seen, new_items, session, log,
                             keywords, max_mb, extensions)
            if not found:
                _scrape_website(term, seen, new_items, session, log,
                                keywords, max_mb, extensions)
        except Exception as e:
            log.error(f"[TED] Error for '{term}': {e}")


def _try_api(term, seen, new_items, session, log, keywords, max_mb, extensions) -> bool:
    """Returns True if API worked (even with 0 results)."""
    try:
        r = session.post(
            _API_URL,
            json={"q": term, "scope": "ACTIVE", "limit": 50, "page": 1, "language": "EN"},
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=20,
        )
        if not r.ok:
            log.warning(f"[TED] API returned {r.status_code} — using website fallback")
            return False

        data    = r.json()
        notices = data.get("results", []) or data.get("notices", []) or []
        log.info(f"  {len(notices)} result(s) via API")

        for notice in notices:
            title     = _get_title(notice)
            notice_id = notice.get("noticePublicationId", "")
            if not notice_id or not matches_keywords(title, keywords):
                continue
            link = f"https://ted.europa.eu/en/notice/-/detail/{notice_id}"
            if link in seen:
                continue
            seen.add(link)
            log.info(f"  Found: {title}")
            saved = follow_and_download(link, session, max_mb, extensions, log)
            _record(title, "TED Europa (EU)", link, saved, keywords, new_items)

        return True
    except Exception:
        return False


def _scrape_website(term, seen, new_items, session, log, keywords, max_mb, extensions):
    """Scrape TED public search results page."""
    try:
        r = session.get(
            _WEB_URL,
            params={"q": term, "scope": "ACTIVE"},
            timeout=30,
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/notice/" not in href:
                continue
            abs_url   = urllib.parse.urljoin("https://ted.europa.eu", href)
            link_text = a.get_text(" ", strip=True)
            if not link_text or abs_url in seen:
                continue
            if not matches_keywords(link_text, keywords):
                continue

            seen.add(abs_url)
            log.info(f"  Found (web): {link_text}")
            saved = follow_and_download(abs_url, session, max_mb, extensions, log)
            _record(link_text, "TED Europa (EU)", abs_url, saved, keywords, new_items)

        log.info(f"  Done scraping TED for '{term}'")
    except Exception as e:
        log.error(f"[TED] Website scrape error for '{term}': {e}")


def _record(title, source, url, saved, keywords, new_items):
    row = {
        "date":             datetime.now().strftime("%Y-%m-%d %H:%M"),
        "title":            title,
        "source":           source,
        "url":              url,
        "file":             "; ".join(saved),
        "keywords_matched": matched_kw_string(title, keywords),
    }
    record_csv(row)
    new_items.append(row)


def _get_title(notice: dict) -> str:
    t = notice.get("title") or {}
    if isinstance(t, dict):
        return t.get("en") or next(iter(t.values()), "") or ""
    return str(t)
