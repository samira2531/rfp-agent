import urllib.parse
from pathlib import Path
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from core.utils import (
    matches_keywords, matched_kw_string, unique_path,
    safe_filename, download_file, record_csv,
    DOC_EXTENSIONS, DOWNLOADS_DIR,
    is_detail_page, follow_and_download,
    is_startup_eligible, read_page_text,
    extract_deadline, extract_deadline_from_pdf, is_deadline_past,
)

# Single-word / short UI navigation texts that should never be treated as RFP links
_NAV_TEXTS = {
    "close", "back", "cancel", "menu", "home", "next", "previous", "prev",
    "ok", "submit", "search", "go", "more", "view all", "see all", "load more",
    "read more", "click here", "here", "link", "top", "skip", "login",
    "sign in", "register", "logout", "sign out", "print", "share", "follow",
    "services", "about", "contact", "sitemap", "feedback", "help",
    "what's new", "whats new", "news", "announcements", "announcement",
    "events", "updates", "notifications", "latest", "highlights", "gallery",
    "media", "press", "archive", "careers", "jobs", "vacancies",
    # Section navigation links found on STPI and similar portals
    "archive tenders", "tenders awarded", "awarded tenders", "past tenders",
    "expired tenders", "current tenders", "upcoming tenders", "all tenders",
    "download", "downloads", "view tender", "view rfp", "view document",
    # Common site-navigation links that leak through on NIC / other portals
    "about us", "documents", "groups & divisions", "groups and divisions",
    "divisions", "organisation", "organization", "overview", "introduction",
    "our services", "products", "solutions", "partners", "clients", "team",
    "technologies", "technology", "resources", "publications", "reports",
    # Generic tender lifecycle notices — not standalone RFPs (RECPDCL, STPI, etc.)
    "corrigendum", "corrigendum 1", "corrigendum 2", "corrigendum 3",
    "amendment", "amendment 1", "amendment 2", "amendment-1", "amendment-2",
    "amednment", "amednment 1",  # common misspelling
    "notification for reverse auction", "notification for opening of financial bids",
    "notification for opening of", "pre-notice inviting tender",
    "financial bid", "opening of financial bids", "reverse auction",
    "cancellation notice", "tender cancellation",
}

# Filename fragments that indicate non-tender documents (certificates, policies, etc.)
_SKIP_FILENAME_FRAGMENTS = {
    "certificate", "cert_", "_cert", "gigw", "wqc", "policy", "privacy",
    "terms", "user_manual", "manual", "brochure", "annual_report",
    "calender", "calendar",  # printed calendar printing tenders
}

# Title prefixes that indicate junk link extraction (HTML rendering artifacts)
_JUNK_TITLE_PREFIXES = ("--", "- -", "   ", "\n", "\r")


def fetch_websites(config: dict, seen: set, new_items: list, session, log):
    keywords        = config.get("keywords", [])
    startup_kws     = config.get("startup_filter", {}).get("keywords", [])
    require_startup = config.get("startup_filter", {}).get("enabled", False)
    global_exts     = {e.lower() for e in config.get("downloads", {}).get(
        "document_extensions", list(DOC_EXTENSIONS))}
    max_mb          = config.get("downloads", {}).get("max_file_size_mb", 100)

    for site_cfg in config.get("websites", []):
        url  = (site_cfg.get("url") or "").strip()
        if not url:
            continue
        name      = site_cfg.get("name", url)
        site_exts = {e.lower() for e in site_cfg.get("document_extensions", list(global_exts))}
        log.info(f"[WEB] {name}")

        ssl_verify = site_cfg.get("ssl_verify", True)
        try:
            try:
                r = session.get(url, timeout=30, verify=ssl_verify)
                r.raise_for_status()
            except requests.exceptions.ContentDecodingError:
                r = session.get(url, timeout=30, headers={"Accept-Encoding": "identity"},
                                verify=ssl_verify)
                r.raise_for_status()

            soup = BeautifulSoup(r.text, "lxml")

            for a in soup.find_all("a", href=True):
                href    = a["href"].strip()
                abs_url = urllib.parse.urljoin(url, href)
                parsed  = urllib.parse.urlparse(abs_url)
                ext     = Path(parsed.path).suffix.lower()

                if parsed.scheme not in ("http", "https"):
                    continue
                if abs_url in seen:
                    continue

                link_text = " ".join(a.get_text(" ", strip=True).split())
                context   = f"{link_text} {a.get('title') or ''}"
                # Walk up the DOM until we find a container with meaningful text
                # that's not the entire page body. Cap at 4 levels to avoid
                # polluting context with distant page sections.
                node = a.parent
                for _ in range(4):
                    if node is None or node.name in ("body", "html", "[document]"):
                        break
                    node_text = node.get_text(" ", strip=True)
                    if 60 < len(node_text) < 2000:
                        context += " " + node_text[:500]
                        break
                    if len(node_text) >= 2000:
                        break
                    node = node.parent

                if not matches_keywords(context, keywords):
                    continue

                # ── Case A: direct document link
                if ext in site_exts:
                    # Skip nav/lifecycle link texts (Corrigendum, Amendment, etc.)
                    if link_text.lower() in _NAV_TEXTS:
                        continue
                    # Skip links whose extracted text starts with HTML rendering artifacts
                    if link_text.startswith(_JUNK_TITLE_PREFIXES):
                        continue
                    # Skip known non-tender filenames (certificates, policy docs, etc.)
                    fname_lower = Path(parsed.path).name.lower()
                    if any(frag in fname_lower for frag in _SKIP_FILENAME_FRAGMENTS):
                        continue

                    # Check deadline from listing-page context before downloading
                    ctx_deadline = extract_deadline(context)
                    if is_deadline_past(ctx_deadline):
                        seen.add(abs_url)  # mark seen so we don't retry
                        log.info(f"  Skipped expired (deadline {ctx_deadline}): {link_text[:60]}")
                        continue

                    seen.add(abs_url)

                    if require_startup and startup_kws:
                        if not is_startup_eligible(context, startup_kws):
                            log.info(f"  Skipped doc (not startup eligible): {link_text}")
                            continue

                    generic_labels = {"view pdf", "download", "download as zip file",
                                      "download file", "view", "open", "view document"}
                    if link_text.lower() in generic_labels:
                        title_str = context.replace(link_text, "").strip()[:120] or link_text
                    else:
                        title_str = link_text

                    fname      = safe_filename(title_str or Path(parsed.path).stem) + ext
                    dest       = DOWNLOADS_DIR / fname
                    actual     = download_file(abs_url, dest, session, max_mb, log, ssl_verify=ssl_verify)

                    # If listing context had no deadline, try reading the PDF
                    deadline = ctx_deadline
                    if actual and not deadline:
                        deadline = extract_deadline_from_pdf(actual)
                    if is_deadline_past(deadline):
                        log.info(f"  Skipped expired (PDF deadline {deadline}): {title_str[:60]}")
                        try: actual.unlink()
                        except Exception: pass
                        continue

                    row = {
                        "date":             datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "title":            title_str or fname,
                        "source":           name,
                        "url":              abs_url,
                        "file":             str(actual) if actual else "",
                        "keywords_matched": matched_kw_string(context, keywords),
                        "deadline":         deadline,
                    }
                    record_csv(row)
                    new_items.append(row)
                    log.info(f"  + {title_str}")

                # ── Case B: HTML detail page — follow it, check startup, download docs
                elif ext in ("", ".htm", ".html", ".aspx", ".php") and is_detail_page(
                        abs_url, extra_patterns=site_cfg.get("detail_patterns")):

                    # Skip pure navigation links (Close, Back, Services, etc.)
                    if link_text.lower() in _NAV_TEXTS:
                        continue
                    # Skip links whose extracted text starts with HTML rendering artifacts
                    if link_text.startswith(_JUNK_TITLE_PREFIXES):
                        continue
                    # Also skip very short or empty link texts with no title attr
                    if len(link_text) < 8 and not a.get("title"):
                        continue

                    seen.add(abs_url)
                    log.info(f"  Following: {link_text or abs_url}")

                    if require_startup and startup_kws:
                        page_text = read_page_text(abs_url, session, log)
                        if not is_startup_eligible(page_text, startup_kws):
                            log.info(f"  Skipped (not startup eligible): {link_text}")
                            continue

                    saved, deadline = follow_and_download(abs_url, session, max_mb, site_exts, log,
                                                         ssl_verify=ssl_verify)
                    deadline = deadline or extract_deadline(context)
                    if not saved:
                        log.info(f"  No documents found at: {link_text or abs_url}")
                        continue
                    if is_deadline_past(deadline):
                        log.info(f"  Skipped expired (deadline {deadline}): {link_text[:60]}")
                        for fp in saved:
                            try: Path(fp).unlink()
                            except Exception: pass
                        continue
                    row = {
                        "date":             datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "title":            link_text or abs_url,
                        "source":           name,
                        "url":              abs_url,
                        "file":             "; ".join(saved),
                        "keywords_matched": matched_kw_string(context, keywords),
                        "deadline":         deadline,
                    }
                    record_csv(row)
                    new_items.append(row)

        except Exception as e:
            log.error(f"[WEB] Error — {name}: {e}")
