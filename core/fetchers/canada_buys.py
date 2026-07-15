"""
CanadaBuys — Federal Canadian procurement.
Scrapes the public tender search page (no login, no API key).
"""

import time
from datetime import datetime

from bs4 import BeautifulSoup

from core.utils import (
    matches_keywords, matched_kw_string,
    follow_and_download, record_csv,
    DOC_EXTENSIONS, is_detail_page,
)

SEARCH_URL = "https://canadabuys.canada.ca/en/tender-opportunities"


def fetch_canada_buys(config: dict, seen: set, new_items: list, session, log):
    cfg = config.get("canada_buys", {})
    if not cfg.get("enabled", False):
        return

    keywords   = config.get("keywords", [])
    max_mb     = config.get("downloads", {}).get("max_file_size_mb", 100)
    extensions = {e.lower() for e in config.get("downloads", {}).get(
        "document_extensions", list(DOC_EXTENSIONS))}

    # Use a single combined search to avoid rate-limiting
    primary_term = (cfg.get("search_terms") or keywords or ["managed services"])[0]
    search_terms = [primary_term]

    for i, term in enumerate(search_terms):
        if i > 0:
            time.sleep(5)   # polite delay between requests
        log.info(f"[CANADA] Searching: '{term}'")
        try:
            r = session.get(
                SEARCH_URL,
                params={"keywords": term, "status": "active"},
                timeout=30,
            )
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "lxml")

            # Find all tender listing links
            for a in soup.find_all("a", href=True):
                href    = a["href"].strip()
                if not href.startswith("http"):
                    href = "https://canadabuys.canada.ca" + href
                if href in seen:
                    continue

                link_text = a.get_text(" ", strip=True)
                context   = link_text
                parent    = a.find_parent(["td", "tr", "li", "div", "article"])
                if parent:
                    context += " " + parent.get_text(" ", strip=True)[:300]

                if not matches_keywords(context, keywords):
                    continue
                if not (is_detail_page(href) or "tender-notice" in href):
                    continue

                seen.add(href)
                log.info(f"  Found: {link_text}")

                saved = follow_and_download(href, session, max_mb, extensions, log)

                row = {
                    "date":             datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "title":            link_text or href,
                    "source":           "CanadaBuys (Federal Canada)",
                    "url":              href,
                    "file":             "; ".join(saved),
                    "keywords_matched": matched_kw_string(context, keywords),
                }
                record_csv(row)
                new_items.append(row)

        except Exception as e:
            log.error(f"[CANADA] Error for '{term}': {e}")
