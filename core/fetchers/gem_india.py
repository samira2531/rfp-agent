"""
GeM India (Government e-Marketplace) fetcher.

Three-tier strategy (tries each in order):
  1. BidPlus /bidlists  — AJAX JSON endpoint used by the React front-end
  2. BidPlus advance-search — GET HTML/JSON endpoint with keyword param
  3. BidPlus POST API  — legacy getBidlistByBidSearch endpoint
"""

import re
import json
import urllib.parse
import time
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup

from core.utils import (
    matches_keywords, matched_kw_string, is_startup_eligible,
    follow_and_download, record_csv, safe_filename,
    download_file, unique_path, DOC_EXTENSIONS, DOWNLOADS_DIR,
)

GEM_BASE       = "https://bidplus.gem.gov.in"
GEM_BIDLISTS   = f"{GEM_BASE}/bidlists"                      # AJAX listing endpoint
GEM_ADVANCE    = f"{GEM_BASE}/advance-search"
GEM_BID_SEARCH = f"{GEM_BASE}/home/getBidlistByBidSearch"    # POST fallback
GEM_BID_VIEW   = f"{GEM_BASE}/bid/view/BID/"

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
    "Referer": f"{GEM_BASE}/all-bids",
}

# GeM service category codes relevant to IT managed services
_GEM_CATEGORIES = [
    "IT Services",
    "Software",
    "Managed Services",
    "Networking",
    "Cloud Services",
    "Cybersecurity",
    "Annual Maintenance Contract",
    "Facility Management",
]

_GEM_SEARCH_TERMS = [
    "managed services",
    "IT services",
    "annual maintenance",
    "network management",
    "cybersecurity",
    "cloud services",
    "software",
    "infrastructure",
]


def fetch_gem(config: dict, seen: set, new_items: list, session, log):
    cfg = config.get("gem", {})
    if not cfg.get("enabled", True):
        return

    keywords        = config.get("keywords", [])
    startup_kws     = config.get("startup_filter", {}).get("keywords", [])
    require_startup = config.get("startup_filter", {}).get("enabled", False)
    max_mb          = config.get("downloads", {}).get("max_file_size_mb", 100)
    extensions      = {e.lower() for e in config.get("downloads", {}).get(
        "document_extensions", list(DOC_EXTENSIONS))}

    log.info("[GeM] Fetching India GeM bids via BidPlus")

    bids = (
        _fetch_via_bidlists(session, log)
        or _fetch_via_advance_search(session, log)
        or _fetch_via_post_api(session, log)
    )

    log.info(f"[GeM] {len(bids)} candidate bid(s) found")
    saved_count = 0

    for bid in bids:
        bid_num    = bid.get("bid_number") or bid.get("bidNumber") or bid.get("id") or ""
        title      = (bid.get("title") or bid.get("bid_title") or
                      bid.get("bidTitle") or str(bid_num))
        detail_url = bid.get("url") or (
            f"{GEM_BID_VIEW}{bid_num}" if bid_num else "")

        if not detail_url or detail_url in seen:
            continue
        context = f"{title} {bid.get('category', '')} {bid.get('ministry', '')}"
        if not matches_keywords(context, keywords):
            log.info(f"  Skipped (no keyword match): {title[:60]}")
            continue

        seen.add(detail_url)
        log.info(f"  Processing: {title[:60]}")

        try:
            dr = session.get(detail_url, timeout=30, headers=_BROWSER_HEADERS)
            if not dr.ok:
                log.warning(f"  Detail page failed ({dr.status_code}): {detail_url}")
                continue
            detail_soup = BeautifulSoup(dr.text, "lxml")
            full_text   = detail_soup.get_text(" ", strip=True)

            if require_startup and startup_kws:
                if not is_startup_eligible(full_text, startup_kws):
                    log.info(f"  Skipped (not startup eligible): {title[:60]}")
                    continue

            saved = []
            for doc_a in detail_soup.find_all("a", href=True):
                doc_href = doc_a["href"].strip()
                doc_url  = urllib.parse.urljoin(GEM_BASE, doc_href)
                ext      = Path(urllib.parse.urlparse(doc_url).path).suffix.lower()
                if ext in extensions:
                    link_text = doc_a.get_text(" ", strip=True)
                    fname = safe_filename(
                        link_text or Path(urllib.parse.urlparse(doc_url).path).stem
                    ) + ext
                    dest = DOWNLOADS_DIR / fname
                    if download_file(doc_url, dest, session, max_mb, log):
                        saved.append(str(unique_path(dest)))

            kw_match = matched_kw_string(context, keywords)
            row = {
                "date":             datetime.now().strftime("%Y-%m-%d %H:%M"),
                "title":            title,
                "source":           "GeM India",
                "url":              detail_url,
                "file":             "; ".join(saved),
                "keywords_matched": kw_match,
            }
            record_csv(row)
            new_items.append(row)
            saved_count += 1
            time.sleep(1)

        except Exception as e:
            log.error(f"  Error processing GeM bid {detail_url}: {e}")

    log.info(f"[GeM] {saved_count} bid(s) recorded")


# ── Tier 1: BidPlus AJAX /bidlists endpoint ───────────────────────────────────

def _fetch_via_bidlists(session, log) -> list:
    """
    Call the BidPlus React app's internal AJAX endpoint directly.
    Tries page 1-3 for each category with X-Requested-With header.
    """
    bids = []
    seen_ids: set = set()

    for term in _GEM_SEARCH_TERMS[:4]:   # limit to keep run time reasonable
        for page in range(1, 4):
            try:
                r = session.get(
                    GEM_BIDLISTS,
                    params={
                        "bid_status": "1",      # 1 = active bids
                        "page_no":    str(page),
                        "search_bid_file": term,
                        "cat": "",
                    },
                    headers={
                        **_BROWSER_HEADERS,
                        "Accept": "application/json, text/javascript, */*; q=0.01",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    timeout=25,
                )
                if not r.ok:
                    break

                # JSON response?
                try:
                    data = r.json()
                    items = (
                        data if isinstance(data, list)
                        else data.get("data", [])
                        or data.get("bids", [])
                        or data.get("result", [])
                        or []
                    )
                    if not items:
                        break
                    for item in items:
                        bid_id = str(
                            item.get("bidNumber") or item.get("bid_number")
                            or item.get("id") or ""
                        )
                        if bid_id and bid_id not in seen_ids:
                            seen_ids.add(bid_id)
                            bids.append({
                                "bid_number": bid_id,
                                "title":    (item.get("bidTitle") or
                                             item.get("bid_title") or
                                             item.get("title") or bid_id),
                                "category": item.get("category", ""),
                                "ministry": item.get("ministry", ""),
                                "url": item.get("url") or f"{GEM_BID_VIEW}{bid_id}",
                            })
                    log.info(f"[GeM] /bidlists '{term}' page {page}: {len(items)} bid(s)")
                    if len(items) < 10:
                        break   # last page
                    continue
                except (ValueError, KeyError):
                    pass

                # HTML fallback — parse bid links from React-rendered HTML
                soup = BeautifulSoup(r.text, "lxml")
                found = _parse_gem_html(soup, seen_ids)
                bids.extend(found)
                if found:
                    log.info(f"[GeM] /bidlists HTML '{term}' page {page}: {len(found)} bid(s)")
                else:
                    break   # no bids on this page

            except Exception as e:
                log.warning(f"[GeM] /bidlists '{term}' p{page}: {e}")
                break

    return bids


# ── Tier 2: advance-search ─────────────────────────────────────────────────────

def _fetch_via_advance_search(session, log) -> list:
    bids: list = []
    seen_ids: set = set()
    for term in _GEM_SEARCH_TERMS:
        try:
            url = (f"{GEM_ADVANCE}?searchType=bid-search"
                   f"&text={urllib.parse.quote(term)}")
            r = session.get(url, headers=_BROWSER_HEADERS, timeout=25)
            if not r.ok:
                continue

            try:
                data  = r.json()
                items = (data if isinstance(data, list)
                         else data.get("data", []) or data.get("bids", []))
                for item in items:
                    bid_id = str(item.get("bidNumber") or item.get("id") or "")
                    if bid_id and bid_id not in seen_ids:
                        seen_ids.add(bid_id)
                        bids.append({
                            "bid_number": bid_id,
                            "title": item.get("bidTitle") or item.get("title") or bid_id,
                        })
                if items:
                    log.info(f"[GeM] advance-search '{term}': {len(items)} result(s)")
                    continue
            except Exception:
                pass

            soup  = BeautifulSoup(r.text, "lxml")
            found = _parse_gem_html(soup, seen_ids)
            bids.extend(found)
            if found:
                log.info(f"[GeM] advance-search HTML '{term}': {len(found)} bid(s)")

        except Exception as e:
            log.warning(f"[GeM] advance-search '{term}': {e}")

    return bids


# ── Tier 3: POST API ───────────────────────────────────────────────────────────

def _fetch_via_post_api(session, log) -> list:
    results = []
    for term in _GEM_SEARCH_TERMS[:3]:
        try:
            r = session.post(
                GEM_BID_SEARCH,
                data={"search_bid_file": term, "bid_status": "1",
                      "bid_number": "", "start_date": "", "end_date": ""},
                headers={
                    **_BROWSER_HEADERS,
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json, text/javascript, */*",
                },
                timeout=20,
            )
            if r.ok:
                try:
                    data  = r.json()
                    items = data if isinstance(data, list) else data.get("data", []) or []
                    if items:
                        log.info(f"[GeM] POST API '{term}': {len(items)} bid(s)")
                        results.extend(items)
                except Exception:
                    pass
        except Exception as e:
            log.warning(f"[GeM] POST API '{term}': {e}")
    return results


# ── HTML parser helper ────────────────────────────────────────────────────────

def _parse_gem_html(soup: BeautifulSoup, seen_ids: set) -> list:
    """Extract bid cards/links from BidPlus HTML page."""
    found = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = re.search(r'GEM[%2F/]+\d{4}[%2F/]+B[%2F/]+(\d+)', href, re.IGNORECASE)
        if not m:
            # also try /bid/view/BID-xxxxxxx pattern
            m2 = re.search(r'/bid/view/BID[/-]?(\d+)', href, re.IGNORECASE)
            if not m2:
                continue
            bid_id = m2.group(1)
        else:
            bid_id = m.group(1)

        if bid_id in seen_ids:
            continue
        seen_ids.add(bid_id)

        title = a.get_text(" ", strip=True)
        if not title or len(title) < 4:
            # try parent element for context
            parent = a.find_parent(["div", "td", "li"])
            if parent:
                title = parent.get_text(" ", strip=True)[:120]
        found.append({
            "bid_number": bid_id,
            "title":      title or f"GEM/B/{bid_id}",
            "url":        urllib.parse.urljoin(GEM_BASE, href),
        })

    # Also scan script tags for embedded JSON
    for script in soup.find_all("script"):
        txt = script.string or ""
        for m in re.finditer(
            r'"bidNumber"\s*:\s*"([^"]+)".*?"bidTitle"\s*:\s*"([^"]+)"', txt
        ):
            bid_id = m.group(1)
            if bid_id not in seen_ids:
                seen_ids.add(bid_id)
                found.append({"bid_number": bid_id, "title": m.group(2)})

    return found
