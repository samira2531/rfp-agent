"""
RFP Agent — orchestrates all fetchers, saves state, sends notification.
Entry point: run_agent.py
"""

import logging
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests

from core.utils import (
    ROOT_DIR, DOWNLOADS_DIR, DATA_DIR, LOGS_DIR,
    load_config, load_seen, save_seen,
)
from core.fetchers.rss         import fetch_rss
from core.fetchers.scraper     import fetch_websites
from core.fetchers.email_imap  import fetch_email
from core.fetchers.sam_gov     import fetch_sam_gov
from core.fetchers.gem_india   import fetch_gem


def setup_logging(log_filename: str) -> logging.Logger:
    LOGS_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(LOGS_DIR / log_filename, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    return logging.getLogger("rfp_agent")


def send_notification(config: dict, new_items: list, log):
    cfg      = config.get("notifications", {})
    if not cfg.get("enabled") or not new_items:
        return

    smtp      = cfg.get("smtp_server", "")
    port      = cfg.get("smtp_port", 587)
    username  = cfg.get("username", "")
    password  = cfg.get("password", "")
    from_addr = cfg.get("from_email") or username
    to_addrs  = cfg.get("to_emails") or []

    if not (smtp and username and password and to_addrs):
        log.warning("Notifications enabled but SMTP not fully configured.")
        return

    rows_html = "\n".join(
        f"<tr>"
        f"<td style='padding:6px'>{r['date']}</td>"
        f"<td style='padding:6px'>{r['title']}</td>"
        f"<td style='padding:6px'>{r['source']}</td>"
        f"<td style='padding:6px'><a href='{r['url']}'>{(r['url'] or 'N/A')[:60]}</a></td>"
        f"</tr>"
        for r in new_items
    )
    body = f"""<html><body style='font-family:Arial,sans-serif'>
<h2>RFP Daily Summary — {datetime.now().strftime('%Y-%m-%d')}</h2>
<p><strong>{len(new_items)}</strong> new RFP(s) found.</p>
<table border='1' cellpadding='0' cellspacing='0' style='border-collapse:collapse'>
<tr style='background:#1a1a2e;color:white'>
  <th style='padding:8px'>Date</th><th style='padding:8px'>Title</th>
  <th style='padding:8px'>Source</th><th style='padding:8px'>Link</th>
</tr>
{rows_html}
</table></body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[RFP Agent] {len(new_items)} new RFP(s) — {datetime.now().strftime('%Y-%m-%d')}"
    msg["From"]    = from_addr
    msg["To"]      = ", ".join(to_addrs)
    msg.attach(MIMEText(body, "html"))

    try:
        with smtplib.SMTP(smtp, port) as s:
            s.ehlo(); s.starttls(); s.login(username, password)
            s.sendmail(from_addr, to_addrs, msg.as_string())
        log.info("Summary email sent.")
    except Exception as e:
        log.error(f"Notification failed: {e}")


def main():
    config = load_config()
    log    = setup_logging(config.get("output", {}).get("log_file", "rfp_agent.log"))

    log.info("=" * 60)
    log.info("RFP Agent starting")
    log.info("=" * 60)

    DOWNLOADS_DIR.mkdir(exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True)

    session = requests.Session()
    session.headers["User-Agent"] = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    )

    seen      = load_seen()
    new_items = []

    fetch_gem(config, seen, new_items, session, log)
    fetch_rss(config, seen, new_items, session, log)
    fetch_websites(config, seen, new_items, session, log)
    fetch_email(config, seen, new_items, log)
    fetch_sam_gov(config, seen, new_items, session, log)

    save_seen(seen)

    if new_items:
        log.info(f"Done — {len(new_items)} new RFP(s) found.")
        send_notification(config, new_items, log)
    else:
        log.info("Done — no new RFPs found.")

    log.info("=" * 60)
