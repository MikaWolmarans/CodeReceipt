import base64
import logging
import re

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


def _split_repo_name(repo_name: str) -> tuple[str, str]:
    """Split repo name into main (white) and accent (yellow) portions for the title."""
    cleaned = re.sub(r'[-_]+', ' ', repo_name).strip()
    parts = cleaned.split()
    if len(parts) >= 2:
        accent = parts[-1].capitalize()
        main = ' '.join(p.capitalize() for p in parts[:-1])
        return main, accent
    return repo_name, ''


async def send_manual_ready_email(to_email: str, session_id: str, repo_name: str) -> None:
    """Send a 'your manual is ready' email via Resend."""
    settings = get_settings()
    if not settings.resend_api_key:
        logger.warning('RESEND_API_KEY not set — skipping email to %s', to_email)
        return

    download_url = f"{settings.frontend_url}/export/{session_id}"
    repo_main, repo_accent = _split_repo_name(repo_name)
    ticker = ' + YOUR MANUAL IS READY' * 6

    payload = {
        "from": settings.from_email,
        "to": [to_email],
        "subject": f"You built it. Do you understand it? — {repo_name}",
        "html": f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: #0A0A0A; font-family: 'Courier New', monospace; color: #F2EDE3; }}
    .wrap {{ max-width: 600px; margin: 0 auto; background: #0A0A0A; }}

    /* Ticker */
    .ticker {{ background: #E8FF00; padding: 10px 0; overflow: hidden; white-space: nowrap; }}
    .ticker-text {{ font-family: 'Courier New', monospace; font-size: 11px; font-weight: 700; letter-spacing: 0.15em; text-transform: uppercase; color: #0A0A0A; }}

    /* Body */
    .body {{ border-left: 6px solid #E8FF00; padding: 48px 40px; }}
    .eyebrow {{ font-size: 10px; letter-spacing: 0.25em; text-transform: uppercase; color: rgba(242,237,227,0.35); margin-bottom: 32px; }}
    .badge {{ display: inline-flex; align-items: center; gap: 8px; font-size: 11px; font-weight: 700; letter-spacing: 0.2em; text-transform: uppercase; color: #E8FF00; margin-bottom: 20px; }}
    .badge-icon {{ width: 0; height: 0; border-top: 5px solid transparent; border-bottom: 5px solid transparent; border-left: 9px solid #E8FF00; }}

    /* Title */
    .title {{ font-size: 56px; font-weight: 900; letter-spacing: -0.03em; line-height: 0.92; text-transform: uppercase; margin-bottom: 32px; }}
    .title-main {{ color: #ffffff; display: block; }}
    .title-accent {{ color: #E8FF00; display: block; }}
    .subtitle {{ font-size: 14px; letter-spacing: 0.15em; text-transform: uppercase; color: rgba(242,237,227,0.4); margin-bottom: 40px; }}

    /* CTA */
    .cta-wrap {{ margin-bottom: 40px; }}
    .cta {{ display: inline-block; background: #E8FF00; color: #0A0A0A; text-decoration: none; padding: 16px 32px; font-family: 'Courier New', monospace; font-weight: 700; font-size: 12px; letter-spacing: 0.12em; text-transform: uppercase; }}

    /* Footer */
    .footer {{ border-top: 1px solid rgba(242,237,227,0.1); padding-top: 24px; margin-top: 8px; font-size: 10px; letter-spacing: 0.08em; color: rgba(242,237,227,0.25); line-height: 1.8; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="ticker">
      <span class="ticker-text">{ticker}</span>
    </div>
    <div class="body">
      <p class="eyebrow">// CodeReceipt &middot; Owner's Manual</p>
      <p class="badge"><span class="badge-icon"></span> Manual Complete</p>
      <div class="title">
        <span class="title-main">{repo_main}</span>
        <span class="title-accent">{repo_accent}</span>
      </div>
      <p class="subtitle">Owner's Manual</p>
      <div class="cta-wrap">
        <a href="{download_url}" class="cta">&darr; Download Your Manual</a>
      </div>
      <div class="footer">
        Link expires in 24 hours.<br>
        You're receiving this because you requested a manual at codereceipt.site.
      </div>
    </div>
  </div>
</body>
</html>""",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json=payload,
        )
    if response.status_code >= 400:
        logger.error('Resend API error %s for %s: %s', response.status_code, to_email, response.text)
    else:
        logger.info('Email sent to %s (status %s)', to_email, response.status_code)


async def send_paid_manual_email(
    to_email: str, session_id: str, repo_name: str, pdf_bytes: bytes
) -> None:
    """Send the paid Owner's Manual email with PDF attached via Resend."""
    settings = get_settings()
    if not settings.resend_api_key:
        logger.warning('RESEND_API_KEY not set — skipping paid email to %s', to_email)
        return

    download_url = f"{settings.frontend_url}/export/{session_id}"
    repo_main, repo_accent = _split_repo_name(repo_name)
    ticker = " + OWNER'S MANUAL DELIVERED" * 6
    pdf_b64 = base64.b64encode(pdf_bytes).decode('ascii')
    safe_filename = re.sub(r'[^a-zA-Z0-9_-]', '_', repo_name)

    payload = {
        "from": settings.from_email,
        "to": [to_email],
        "subject": f"Your {repo_name} Owner's Manual is ready",
        "attachments": [
            {
                "filename": f"{safe_filename}_owners_manual.pdf",
                "content": pdf_b64,
            }
        ],
        "html": f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: #0A0A0A; font-family: 'Courier New', monospace; color: #F2EDE3; }}
    .wrap {{ max-width: 600px; margin: 0 auto; background: #0A0A0A; }}
    .ticker {{ background: #E8FF00; padding: 10px 0; overflow: hidden; white-space: nowrap; }}
    .ticker-text {{ font-family: 'Courier New', monospace; font-size: 11px; font-weight: 700; letter-spacing: 0.15em; text-transform: uppercase; color: #0A0A0A; }}
    .body {{ border-left: 6px solid #E8FF00; padding: 48px 40px; }}
    .eyebrow {{ font-size: 10px; letter-spacing: 0.25em; text-transform: uppercase; color: rgba(242,237,227,0.35); margin-bottom: 32px; }}
    .badge {{ display: inline-flex; align-items: center; gap: 8px; font-size: 11px; font-weight: 700; letter-spacing: 0.2em; text-transform: uppercase; color: #E8FF00; margin-bottom: 20px; }}
    .badge-icon {{ width: 0; height: 0; border-top: 5px solid transparent; border-bottom: 5px solid transparent; border-left: 9px solid #E8FF00; }}
    .title {{ font-size: 56px; font-weight: 900; letter-spacing: -0.03em; line-height: 0.92; text-transform: uppercase; margin-bottom: 32px; }}
    .title-main {{ color: #ffffff; display: block; }}
    .title-accent {{ color: #E8FF00; display: block; }}
    .subtitle {{ font-size: 14px; letter-spacing: 0.15em; text-transform: uppercase; color: rgba(242,237,227,0.4); margin-bottom: 40px; }}
    .note {{ font-size: 12px; line-height: 1.7; color: rgba(242,237,227,0.6); margin-bottom: 32px; }}
    .cta-wrap {{ margin-bottom: 32px; }}
    .cta {{ display: inline-block; background: #E8FF00; color: #0A0A0A; text-decoration: none; padding: 16px 32px; font-family: 'Courier New', monospace; font-weight: 700; font-size: 12px; letter-spacing: 0.12em; text-transform: uppercase; }}
    .rescan {{ font-size: 11px; letter-spacing: 0.1em; color: rgba(242,237,227,0.35); margin-bottom: 32px; }}
    .rescan a {{ color: #E8FF00; text-decoration: none; }}
    .footer {{ border-top: 1px solid rgba(242,237,227,0.1); padding-top: 24px; margin-top: 8px; font-size: 10px; letter-spacing: 0.08em; color: rgba(242,237,227,0.25); line-height: 1.8; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="ticker">
      <span class="ticker-text">{ticker}</span>
    </div>
    <div class="body">
      <p class="eyebrow">// CodeReceipt &middot; Owner's Manual</p>
      <p class="badge"><span class="badge-icon"></span> Paid &mdash; Delivered</p>
      <div class="title">
        <span class="title-main">{repo_main}</span>
        <span class="title-accent">{repo_accent}</span>
      </div>
      <p class="subtitle">Owner's Manual</p>
      <p class="note">
        Your full Owner's Manual is attached to this email as a PDF.<br>
        It covers what you built, how it works, what can break, and how to maintain it.
      </p>
      <div class="cta-wrap">
        <a href="{download_url}" class="cta">&darr; View &amp; Download</a>
      </div>
      <p class="rescan">
        Pushed new code? <a href="https://codereceipt.site">Re-scan your repo</a> for a fresh manual.
      </p>
      <div class="footer">
        Download link valid for 30 days.<br>
        You're receiving this because you purchased a manual at codereceipt.site.
      </div>
    </div>
  </div>
</body>
</html>""",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json=payload,
        )
    if response.status_code >= 400:
        logger.error('Resend paid email error %s for %s: %s', response.status_code, to_email, response.text)
        raise RuntimeError(f'Resend API returned {response.status_code}')
    else:
        logger.info('Paid email sent to %s (status %s)', to_email, response.status_code)
