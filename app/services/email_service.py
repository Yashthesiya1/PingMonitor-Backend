import resend
from app.config import settings

resend.api_key = settings.RESEND_API_KEY


def send_email(to: str, subject: str, html: str) -> bool:
    """Send an email via Resend. Returns True on success."""
    if not settings.RESEND_API_KEY:
        print(f"[EMAIL] Skipped (no API key): {subject} -> {to}")
        return False

    try:
        resend.Emails.send({
            "from": settings.EMAIL_FROM,
            "to": [to],
            "subject": subject,
            "html": html,
        })
        print(f"[EMAIL] Sent: {subject} -> {to}")
        return True
    except Exception as e:
        print(f"[EMAIL] Failed: {subject} -> {to} - {e}")
        return False


def send_test_email(to: str) -> bool:
    return send_email(
        to=to,
        subject="[TEST] PingMonitor - Test Notification",
        html="""
        <div style="font-family:sans-serif;max-width:450px;margin:20px auto;padding:24px;border:1px solid #e5e5ea;border-radius:12px;">
            <h2 style="color:#6c5ce7;margin:0 0 12px;">Test Notification</h2>
            <p style="color:#333;margin:0 0 8px;">This is a test from PingMonitor.</p>
            <p style="color:#8e8ea0;font-size:13px;margin:0;">If you received this, your email channel is working correctly.</p>
        </div>
        """,
    )


def send_down_email(to: str, endpoint_name: str, endpoint_url: str, cause: str) -> bool:
    return send_email(
        to=to,
        subject=f"[DOWN] {endpoint_name} is not responding",
        html=f"""
        <div style="font-family:sans-serif;max-width:560px;margin:40px auto;background:#fff;border-radius:12px;border:1px solid #e5e5ea;overflow:hidden;">
            <div style="background:linear-gradient(135deg,#6c5ce7,#4a3db0);padding:28px 32px;text-align:center;">
                <h1 style="margin:0;color:#fff;font-size:20px;font-weight:700;">PingMonitor</h1>
            </div>
            <div style="background:#fef2f2;border-bottom:1px solid #fecaca;padding:16px 32px;text-align:center;">
                <span style="display:inline-block;background:#ef4444;color:#fff;font-size:11px;font-weight:700;padding:3px 10px;border-radius:20px;text-transform:uppercase;">Endpoint Down</span>
            </div>
            <div style="padding:32px;">
                <h2 style="margin:0 0 8px;font-size:18px;color:#1a1a2e;">{endpoint_name} is down</h2>
                <p style="margin:0 0 24px;color:#8e8ea0;font-size:14px;">We detected that your endpoint is not responding.</p>
                <div style="background:#f8f8fa;border-radius:8px;padding:16px;margin-bottom:24px;">
                    <table style="width:100%;border-collapse:collapse;">
                        <tr><td style="padding:6px 0;color:#8e8ea0;font-size:13px;">URL</td><td style="padding:6px 0;color:#1a1a2e;font-size:13px;text-align:right;font-family:monospace;">{endpoint_url}</td></tr>
                        <tr><td style="padding:6px 0;color:#8e8ea0;font-size:13px;">Cause</td><td style="padding:6px 0;color:#ef4444;font-size:13px;text-align:right;">{cause}</td></tr>
                    </table>
                </div>
                <a href="https://ping.yashai.me/dashboard/endpoints" style="display:inline-block;background:#6c5ce7;color:#fff;text-decoration:none;padding:12px 24px;border-radius:8px;font-size:14px;font-weight:600;">View Dashboard</a>
            </div>
        </div>
        """,
    )


def send_recovery_email(to: str, endpoint_name: str, endpoint_url: str, duration: str) -> bool:
    return send_email(
        to=to,
        subject=f"[RECOVERED] {endpoint_name} is back up",
        html=f"""
        <div style="font-family:sans-serif;max-width:560px;margin:40px auto;background:#fff;border-radius:12px;border:1px solid #e5e5ea;overflow:hidden;">
            <div style="background:linear-gradient(135deg,#6c5ce7,#4a3db0);padding:28px 32px;text-align:center;">
                <h1 style="margin:0;color:#fff;font-size:20px;font-weight:700;">PingMonitor</h1>
            </div>
            <div style="background:#f0fdf4;border-bottom:1px solid #bbf7d0;padding:16px 32px;text-align:center;">
                <span style="display:inline-block;background:#22c55e;color:#fff;font-size:11px;font-weight:700;padding:3px 10px;border-radius:20px;text-transform:uppercase;">Recovered</span>
            </div>
            <div style="padding:32px;">
                <h2 style="margin:0 0 8px;font-size:18px;color:#1a1a2e;">{endpoint_name} is back up</h2>
                <p style="margin:0 0 24px;color:#8e8ea0;font-size:14px;">Your endpoint has recovered and is responding normally.</p>
                <div style="background:#f8f8fa;border-radius:8px;padding:16px;margin-bottom:24px;">
                    <table style="width:100%;border-collapse:collapse;">
                        <tr><td style="padding:6px 0;color:#8e8ea0;font-size:13px;">URL</td><td style="padding:6px 0;color:#1a1a2e;font-size:13px;text-align:right;font-family:monospace;">{endpoint_url}</td></tr>
                        <tr><td style="padding:6px 0;color:#8e8ea0;font-size:13px;">Downtime</td><td style="padding:6px 0;color:#1a1a2e;font-size:13px;text-align:right;">{duration}</td></tr>
                    </table>
                </div>
                <a href="https://ping.yashai.me/dashboard/endpoints" style="display:inline-block;background:#6c5ce7;color:#fff;text-decoration:none;padding:12px 24px;border-radius:8px;font-size:14px;font-weight:600;">View Dashboard</a>
            </div>
        </div>
        """,
    )
