import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings

logger = logging.getLogger("fpga_remote_lab.email")


def send_two_factor_code(to_email: str, username: str, code: str) -> bool:
    """Send the 2FA code by email. Falls back to logging when SMTP isn't
    configured yet, so auth flows are testable before real credentials exist.
    """
    if not settings.smtp_host:
        logger.info("2FA code for %s <%s>: %s (SMTP not configured, logging only)", username, to_email, code)
        return True

    message = MIMEMultipart("alternative")
    message["Subject"] = "Your verification code - FPGA Remote Lab"
    message["From"] = f"{settings.mail_from_name} <{settings.mail_from_email}>"
    message["To"] = to_email

    # Derived from the actual TTL setting so this text can't drift out of
    # sync with the real expiry again (it previously said "1 minute" no
    # matter what the configured TTL was).
    expiry_minutes = settings.two_factor_code_ttl_seconds / 60
    expiry_text = f"{expiry_minutes:g} minute{'s' if expiry_minutes != 1 else ''}"

    text_body = (
        f"Hi {username},\n\n"
        f"Use this verification code to finish signing in: {code}\n"
        f"It expires in {expiry_text}.\n\n"
        "If you didn't request this, you can safely ignore this email.\n\n"
        "- FPGA Remote Lab (H-BRS)"
    )
    # Email HTML is deliberately old-school: table-based layout with only
    # inline styles (no <style> block, no flexbox/grid), because many mail
    # clients strip <head>/<style> and don't support modern CSS. Colors
    # mirror the app's theme (indigo primary). No external images - the
    # server isn't publicly reachable, so a hosted logo wouldn't load; the
    # brand is set in text instead.
    html_body = f"""
    <!doctype html>
    <html>
      <body style="margin:0; padding:0; background-color:#f1f5f9;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
               style="background-color:#f1f5f9; padding:32px 12px;">
          <tr>
            <td align="center">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                     style="max-width:480px; background-color:#ffffff; border:1px solid #e2e8f0;
                            border-radius:12px; overflow:hidden;
                            font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
                <tr>
                  <td style="background-color:#4f46e5; padding:20px 32px;">
                    <span style="color:#ffffff; font-size:18px; font-weight:700;">FPGA Remote Lab</span>
                  </td>
                </tr>
                <tr>
                  <td style="padding:32px;">
                    <p style="margin:0 0 8px; font-size:16px; color:#0f172a;">Hi <strong>{username}</strong>,</p>
                    <p style="margin:0 0 24px; font-size:15px; color:#475569; line-height:1.5;">
                      Use this verification code to finish signing in:
                    </p>
                    <div style="text-align:center; margin:0 0 24px;">
                      <span style="display:inline-block; background-color:#eef2ff; border:1px solid #c7d2fe;
                                   border-radius:10px; padding:16px 28px 16px 36px;
                                   font-family:'Courier New',monospace; font-size:32px; font-weight:700;
                                   letter-spacing:8px; color:#4338ca;">{code}</span>
                    </div>
                    <p style="margin:0 0 4px; font-size:14px; color:#64748b;">
                      This code expires in <strong>{expiry_text}</strong>.
                    </p>
                    <p style="margin:0; font-size:14px; color:#64748b;">
                      If you didn't request it, you can safely ignore this email.
                    </p>
                  </td>
                </tr>
                <tr>
                  <td style="padding:18px 32px; border-top:1px solid #e2e8f0; background-color:#f8fafc;">
                    <span style="font-size:12px; color:#94a3b8;">
                      H-BRS FPGA Remote Lab &middot; automated message, please do not reply.
                    </span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
        </table>
      </body>
    </html>
    """
    message.attach(MIMEText(text_body, "plain"))
    message.attach(MIMEText(html_body, "html"))

    try:
        if settings.smtp_mode == "ssl":
            server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port)
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port)
            if settings.smtp_mode == "starttls":
                server.starttls()

        with server:
            # A mock server like Mailpit needs no credentials - only
            # authenticate when we actually have a username configured.
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password)
            server.sendmail(settings.mail_from_email, [to_email], message.as_string())
        return True
    except smtplib.SMTPException:
        logger.exception("Failed to send 2FA email to %s", to_email)
        return False
