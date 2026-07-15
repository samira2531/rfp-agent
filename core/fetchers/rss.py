import urllib.parse
from pathlib import Path
from datetime import datetime

import feedparser

from core.utils import (
    matches_keywords, matched_kw_string,
    safe_filename, download_file, record_csv,
    DOC_EXTENSIONS, extract_doc_links,
    follow_and_download, is_startup_eligible, is_india_tender,
    read_page_text, DOWNLOADS_DIR,
)


def fetch_rss(config: dict, seen: set, new_items: list, session, log):
    keywords        = config.get("keywords", [])
    startup_kws     = config.get("startup_filter", {}).get("keywords", [])
    require_startup = config.get("startup_filter", {}).get("enabled", False)
    location_filter = config.get("location_filter", {})
    max_mb        = config.get("downloads", {}).get("max_file_size_mb", 100)
    extensions    = {e.lower() for e in config.get("downloads", {}).get(
        "document_extensions", list(DOC_EXTENSIONS))}

    for feed_cfg in config.get("rss_feeds", []):
        url  = (feed_cfg.get("url") or "").strip()
        if not url:
            continue
        name = feed_cfg.get("name", url)
        log.info(f"[RSS] {name}")
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                title    = getattr(entry, "title",   "") or ""
                link     = getattr(entry, "link",    "") or ""
                summary  = getattr(entry, "summary", "") or ""
                combined = f"{title} {summary}"

                if not link or link in seen:
                    continue
                if not matches_keywords(combined, keywords):
                    continue

                # ── India location filter (fast check on title + summary)
                if not is_india_tender(combined, location_filter):
                    log.info(f"  Skipped (not India): {title}")
                    seen.add(link)
                    continue

                seen.add(link)
                log.info(f"  Found: {title}")

                # ── Check startup eligibility by reading the detail page
                if require_startup and startup_kws:
                    page_text = read_page_text(link, session, log)
                    if not is_startup_eligible(page_text, startup_kws):
                        log.info(f"  Skipped (not startup eligible): {title}")
                        continue
                    log.info(f"  Startup eligible ✓")

                # ── Step 1: direct doc links in feed summary
                saved = []
                for doc_url in extract_doc_links(summary, extensions):
                    if doc_url in seen:
                        continue
                    seen.add(doc_url)
                    ext   = Path(urllib.parse.urlparse(doc_url).path).suffix.lower() or ".pdf"
                    fname = safe_filename(title or Path(urllib.parse.urlparse(doc_url).path).name) + ext
                    dest  = DOWNLOADS_DIR / fname
                    if download_file(doc_url, dest, session, max_mb, log):
                        saved.append(str(dest))

                # ── Step 2: visit detail page and download all attached docs
                if not saved:
                    saved = follow_and_download(link, session, max_mb, extensions, log)

                row = {
                    "date":             datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "title":            title,
                    "source":           name,
                    "url":              link,
                    "file":             "; ".join(saved),
                    "keywords_matched": matched_kw_string(combined, keywords),
                }
                record_csv(row)
                new_items.append(row)

        except Exception as e:
            log.error(f"[RSS] Error — {name}: {e}")
