import httpx

from app.config import get_settings


async def send_manual_ready_email(to_email: str, session_id: str, repo_name: str) -> None:
    """Send a 'your manual is ready' email via Resend."""
    settings = get_settings()
    if not settings.resend_api_key:
        return

    download_url = f"{settings.frontend_url}/export/{session_id}"

    if settings.resend_template_id:
        payload = {
            "from": settings.from_email,
            "to": [to_email],
            "subject": f"Your CodeReceipt manual is ready — {repo_name}",
            "template_id": settings.resend_template_id,
            "variables": {
                "repo_name": repo_name,
                "download_url": download_url,
            },
        }
    else:
        payload = {
            "from": settings.from_email,
            "to": [to_email],
            "subject": f"Your CodeReceipt manual is ready — {repo_name}",
            "html": f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family: 'Courier New', monospace; background: #0A0A0A; color: #F2EDE3; margin: 0; padding: 40px 20px; }}
    .container {{ max-width: 560px; margin: 0 auto; }}
    .header {{ background: #E8FF00; color: #0A0A0A; padding: 16px 24px; font-weight: 700; font-size: 18px; letter-spacing: -0.02em; }}
    .body {{ border: 3px solid #F2EDE3; padding: 32px 24px; margin-top: 0; }}
    .label {{ font-size: 11px; letter-spacing: 0.2em; text-transform: uppercase; opacity: 0.5; margin-bottom: 8px; }}
    .repo {{ font-size: 20px; font-weight: 700; margin-bottom: 24px; color: #E8FF00; }}
    .message {{ font-size: 14px; line-height: 1.7; opacity: 0.8; margin-bottom: 32px; }}
    .btn {{ display: inline-block; background: #E8FF00; color: #0A0A0A; text-decoration: none; padding: 16px 32px; font-weight: 700; font-size: 13px; letter-spacing: 0.1em; text-transform: uppercase; }}
    .footer {{ margin-top: 32px; font-size: 11px; opacity: 0.4; letter-spacing: 0.05em; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">CODERECEIPT</div>
    <div class="body">
      <p class="label">Manual ready for</p>
      <p class="repo">{repo_name}</p>
      <p class="message">
        Your owner's manual has been generated. It contains a plain-English breakdown
        of what was built, how it works, and how to maintain it.
      </p>
      <a href="{download_url}" class="btn">↓ Download Your Manual</a>
      <p class="footer">
        Link expires in 24 hours.<br>
        You're receiving this because you requested a manual at codereceipt.site.
      </p>
    </div>
  </div>
</body>
</html>
""",
        }

    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json=payload,
        )
