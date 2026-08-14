# actions/gmail.py
# Kaizumi — Gmail (send + read recent mail via SMTP/IMAP app password)

import json
import re
import smtplib
import imaplib
import email
import sys
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header
from pathlib import Path

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


CONFIG_PATH = get_base_dir() / "config" / "api_keys.json"


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _creds_error(cfg: dict) -> str | None:
    user = (cfg.get("gmail_user") or "").strip()
    pwd  = (cfg.get("gmail_app_password") or "").strip()
    if not user:
        return ("Gmail is not configured yet, sir. I need your Gmail address "
                "saved as 'gmail_user' in config/api_keys.json.")
    if not pwd:
        return ("Your Gmail app password is missing, sir. Save it as "
                "'gmail_app_password' in config/api_keys.json "
                "(create it at myaccount.google.com → Security → App passwords).")
    return None


def _decode(s: str) -> str:
    if not s:
        return ""
    try:
        parts = decode_header(s)
    except Exception:
        return str(s)
    out = []
    for text, enc in parts:
        try:
            if isinstance(text, bytes):
                text = text.decode(enc or "utf-8", errors="replace")
        except Exception:
            pass
        out.append(str(text))
    return "".join(out)


def _body_snippet(msg) -> str:
    for part in msg.walk():
        if part.get_content_type() == "text/plain":
            try:
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                text = payload.decode(charset, errors="replace")
            except Exception:
                continue
            text = re.sub(r"\s+", " ", text).strip()
            return text[:400]
    return "(no text body)"


def _send_gmail(cfg: dict, to: str, subject: str, body: str) -> str:
    user = (cfg.get("gmail_user") or "").strip()
    pwd  = (cfg.get("gmail_app_password") or "").strip()

    msg = MIMEMultipart("alternative")
    msg["From"]    = user
    msg["To"]      = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as server:
        server.login(user, pwd)
        server.sendmail(user, [to], msg.as_string())
    return f"Email sent to {to} with subject '{subject}'."


def _read_gmail(cfg: dict, limit: int) -> str:
    user = (cfg.get("gmail_user") or "").strip()
    pwd  = (cfg.get("gmail_app_password") or "").strip()
    limit = max(1, min(int(limit or 5), 20))

    with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, timeout=30) as conn:
        conn.login(user, pwd)
        conn.select("INBOX")
        typ, data = conn.search(None, "ALL")
        if typ != "OK" or not data or not data[0]:
            return "No emails in the inbox, sir."
        ids = data[0].split()[-limit:]
        lines = []
        for num in reversed(ids):
            typ, msg_data = conn.fetch(num, "(RFC822)")
            if typ != "OK" or not msg_data:
                continue
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            frm = _decode(msg.get("From", "?"))
            subj = _decode(msg.get("Subject", "(no subject)"))
            lines.append(f"• {frm} — {subj}\n   {_body_snippet(msg)}")
    return "Recent emails:\n" + "\n".join(lines)


def gmail_action(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """Gmail operations: send | read (default: send)"""
    params = parameters or {}
    action = str(params.get("action", "send")).lower().strip()

    cfg = _load_config()
    err = _creds_error(cfg)
    if err:
        return err

    try:
        if action in ("send", "compose"):
            to      = str(params.get("to", "")).strip()
            subject = str(params.get("subject", "")).strip() or "From Kaizumi"
            body    = str(params.get("body", "")).strip()
            if not to:
                return "I need the recipient's email address, sir."
            if not body:
                return "I need the message body, sir."
            return _send_gmail(cfg, to, subject, body)

        if action in ("read", "check", "inbox", "latest"):
            return _read_gmail(cfg, int(params.get("limit", 5)))

        return f"Unknown Gmail action: {action}. Use 'send' or 'read', sir."
    except smtplib.SMTPAuthenticationError:
        return ("Gmail login failed, sir. Make sure 'gmail_app_password' is a "
                "real 16-character app password (not your normal password) and "
                "that 2-Step Verification is enabled for your account.")
    except Exception as e:
        return f"Gmail operation failed: {e}"
