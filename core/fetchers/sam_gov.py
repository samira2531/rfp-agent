import urllib.parse
from pathlib import Path
from datetime import datetime, timedelta

from core.utils import (
    matches_keywords, matched_kw_string, unique_path,
    safe_filename, download_file, record_csv,
    DOC_EXTENSIONS, DOWNLOADS_DIR,
)


def fetch_sam_gov(config: dict, seen: set, new_items: list, session, log):
    cfg = config.get("sam_gov", {})
    if not cfg.get("enabled"):
        return

    api_key      = cfg.get("api_key", "")
    search_terms = cfg.get("search_terms") or [""]
    days_back    = cfg.get("posted_from_days", 1)
    keywords     = config.get("keywords", [])
    max_mb       = config.get("downloads", {}).get("max_file_size_mb", 100)

    if not api_key:
        log.warning("[SAM.GOV] api_key not set — skipping.")
        return

    posted_from = (datetime.now() - timedelta(days=days_back)).strftime("%m/%d/%Y")
    posted_to   = datetime.now().strftime("%m/%d/%Y")

    for term in search_terms:
        params = {
            "api_key":    api_key,
            "postedFrom": posted_from,
            "postedTo":   posted_to,
            "limit":      100,
            "offset":     0,
        }
        if term:
            params["q"] = term

        log.info(f"[SAM.GOV] Searching: '{term or '*'}'")
        try:
            r = session.get(
                "https://api.sam.gov/opportunities/v2/search",
                params=params,
                timeout=30,
            )
            r.raise_for_status()
            opps = r.json().get("opportunitiesData", [])
            log.info(f"  {len(opps)} result(s)")

            for opp in opps:
                notice_id = opp.get("noticeId", "")
                title     = opp.get("title", "")
                link      = opp.get("uiLink") or f"https://sam.gov/opp/{notice_id}/view"

                if link in seen:
                    continue
                if not matches_keywords(f"{title} {opp.get('description', '')}", keywords):
                    continue

                seen.add(link)

                downloaded_file = ""
                for att_url in (opp.get("resourceLinks") or [])[:3]:
                    ext = Path(urllib.parse.urlparse(att_url).path).suffix.lower()
                    if ext not in DOC_EXTENSIONS:
                        continue
                    fname = safe_filename(title) + ext
                    dest  = DOWNLOADS_DIR / fname
                    if download_file(att_url, dest, session, max_mb, log):
                        downloaded_file = str(unique_path(dest))
                        break

                row = {
                    "date":             datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "title":            title,
                    "source":           "SAM.gov",
                    "url":              link,
                    "file":             downloaded_file,
                    "keywords_matched": matched_kw_string(title, keywords),
                }
                record_csv(row)
                new_items.append(row)
                log.info(f"  + {title}")

        except Exception as e:
            log.error(f"[SAM.GOV] Error for '{term}': {e}")
