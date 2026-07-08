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

    text_body = f"Hi {username},\n\nYour verification code is: {code}\nIt expires in 1 minute."
    html_body = f"""
    <html><body>
      <p>Hi <strong>{username}</strong>,</p>
      <p>Your verification code is:</p>
      <h2>{code}</h2>
      <p>It expires in 1 minute.</p>
    </body></html>
    """
    message.attach(MIMEText(text_body, "plain"))
    message.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port) as server:
            server.login(settings.smtp_username, settings.smtp_password)
            server.sendmail(settings.mail_from_email, [to_email], message.as_string())
        return True
    except smtplib.SMTPException:
        logger.exception("Failed to send 2FA email to %s", to_email)
        return False
