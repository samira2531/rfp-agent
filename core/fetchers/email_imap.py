import ssl
import email
import imaplib
import hashlib
import re
from pathlib import Path
from datetime import datetime

from core.utils import (
    matches_keywords, matched_kw_string, unique_path,
    record_csv, DOC_EXTENSIONS, DOWNLOADS_DIR,
)


def fetch_email(config: dict, seen: set, new_items: list, log):
    cfg = config.get("email", {})
    if not cfg.get("enabled"):
        return

    server   = cfg.get("imap_server", "")
    port     = cfg.get("imap_port", 993)
    username = cfg.get("username", "")
    password = cfg.get("password", "")
    folder   = cfg.get("folder", "INBOX")
    subj_kws = cfg.get("subject_keywords", ["RFP"])
    keywords = config.get("keywords", [])
    max_mb   = config.get("downloads", {}).get("max_file_size_mb", 100)

    if not (server and username and password):
        log.warning("[EMAIL] Credentials not configured — skipping.")
        return

    log.info(f"[EMAIL] {username} @ {server}")
    try:
        ctx  = ssl.create_default_context()
        mail = imaplib.IMAP4_SSL(server, port, ssl_context=ctx)
        mail.login(username, password)
        mail.select(folder)

        _, msg_ids = mail.search(None, "UNSEEN")
        ids = msg_ids[0].split()
        log.info(f"  {len(ids)} unread message(s)")

        for msg_id in ids:
            _, data = mail.fetch(msg_id, "(RFC822)")
            msg      = email.message_from_bytes(data[0][1])
            subject  = str(msg.get("Subject", ""))
            sender   = str(msg.get("From", ""))
            date_str = str(msg.get("Date", ""))

            if not any(kw.lower() in subject.lower() for kw in subj_kws):
                continue
            if not matches_keywords(subject, keywords):
                continue

            uid = hashlib.md5(f"{subject}{sender}{date_str}".encode()).hexdigest()
            if uid in seen:
                continue
            seen.add(uid)

            saved = []
            for part in msg.walk():
                if part.get_content_maintype() == "multipart":
                    continue
                disp = str(part.get("Content-Disposition") or "")
                if "attachment" not in disp and "inline" not in disp:
                    continue
                filename = part.get_filename()
                if not filename:
                    continue
                ext = Path(filename).suffix.lower()
                if ext not in DOC_EXTENSIONS:
                    continue
                payload = part.get_payload(decode=True)
                if not payload or len(payload) > max_mb * 1024 * 1024:
                    continue
                safe = re.sub(r"[^\w\s.()\-]", "", Path(filename).stem).strip() + ext
                dest = unique_path(DOWNLOADS_DIR / safe)
                dest.write_bytes(payload)
                saved.append(str(dest))
                log.info(f"  Saved attachment: {dest.name}")

            row = {
                "date":             datetime.now().strftime("%Y-%m-%d %H:%M"),
                "title":            subject,
                "source":           f"Email: {sender}",
                "url":              "",
                "file":             "; ".join(saved),
                "keywords_matched": matched_kw_string(subject, keywords),
            }
            record_csv(row)
            new_items.append(row)

        mail.close()
        mail.logout()

    except Exception as e:
        log.error(f"[EMAIL] Error: {e}")
