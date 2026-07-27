import smtplib
from datetime import datetime
from email.message import EmailMessage
from html import escape

from config import settings


def _deliver(message: EmailMessage) -> None:
    if not settings.smtp_host:
        raise RuntimeError("SMTP is not configured")
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(message)


def send_email(recipient: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from
    message["To"] = recipient
    message.set_content(body)
    _deliver(message)


def send_otp(email: str, code: str) -> None:
    plain = (
        "Your GPU Compute login code\n\n"
        f"{code}\n\n"
        f"This code expires in {settings.otp_minutes} minutes and can only be used once.\n"
        "If you did not request this code, you can safely ignore this email.\n"
    )
    message = EmailMessage()
    message["Subject"] = "Your GPU Compute login code"
    message["From"] = settings.smtp_from
    message["To"] = email
    message.set_content(plain)
    message.add_alternative(
        f"""<!doctype html><html><body style="margin:0;background:#f3f9fc;color:#102532;font-family:Arial,sans-serif">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:32px 16px">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:620px;background:#ffffff;border:1px solid #d5e3eb">
        <tr><td style="padding:24px 28px;background:#25B5FF;color:#102532"><div style="font-size:11px;letter-spacing:1.5px;text-transform:uppercase;opacity:.75">AIML GPU Compute</div><h1 style="margin:7px 0 0;font-size:24px">Confirm your sign-in</h1></td></tr>
        <tr><td style="padding:28px"><p style="margin:0 0 22px;color:#617783">Enter this one-time code in the reservation portal to continue.</p>
        <div style="margin-bottom:7px;font-size:11px;font-weight:bold;letter-spacing:1px;text-transform:uppercase;color:#617783">Login code</div>
        <pre style="margin:0;padding:20px;overflow:auto;background:#102532;color:#ffffff;border-radius:3px;text-align:center;font-family:'JetBrains Mono','SFMono-Regular',Consolas,monospace;font-size:30px;font-weight:700;line-height:1.25;letter-spacing:8px;white-space:pre-wrap">{escape(code)}</pre>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:22px;background:#e5f6ff;border:1px solid #9bdcff"><tr><td style="padding:15px 17px"><strong style="display:block;font-size:14px">Expires in {settings.otp_minutes} minutes</strong><span style="color:#356b89;font-size:12px">This code can only be used once. Never share it with anyone.</span></td></tr></table>
        <p style="margin:22px 0 0;color:#617783;font-size:12px">If you did not request this sign-in code, you can safely ignore this email. No changes will be made to your account.</p>
        </td></tr></table></td></tr></table></body></html>""",
        subtype="html",
    )
    _deliver(message)


def send_credentials(email: str, username: str, password: str, port: int,
                     reservation_start: datetime | None = None,
                     reservation_end: datetime | None = None) -> None:
    command = f"ssh {username}@{settings.server_ip} -p {port}"
    # Separate the address across elements so mail clients do not mistake it for an email link.
    command_html = (
        f"ssh <span>{escape(username)}</span><span>&#64;</span>"
        f"<span>{escape(settings.server_ip)}</span> -p {port}"
    )
    if reservation_start and reservation_end:
        start = reservation_start.astimezone()
        end = reservation_end.astimezone()
        reservation_date = start.strftime("%A, %d %B %Y")
        reservation_time = f'{start.strftime("%I:%M %p").lstrip("0")} – {end.strftime("%I:%M %p").lstrip("0")} {start.tzname() or ""}'.strip()
        schedule_text = f"Reservation: {reservation_date}, {reservation_time}\n"
    else:
        reservation_date = "Scheduled reservation"
        reservation_time = "See the reservation portal for timing"
        schedule_text = ""

    plain = (
        "Your AIML GPU access is ready.\n\n"
        f"{schedule_text}"
        f"SSH command:\n{command}\n\n"
        f"Password:\n{password}\n\n"
        "This password is unique to this reservation. A new password will be issued for your next reservation.\n"
    )
    message = EmailMessage()
    message["Subject"] = f"GPU reservation access · {reservation_date}"
    message["From"] = settings.smtp_from
    message["To"] = email
    message.set_content(plain)
    message.add_alternative(
        f"""<!doctype html><html><body style="margin:0;background:#f3f9fc;color:#102532;font-family:Arial,sans-serif">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:32px 16px">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:620px;background:#ffffff;border:1px solid #d5e3eb">
        <tr><td style="padding:24px 28px;background:#25B5FF;color:#102532"><div style="font-size:11px;letter-spacing:1.5px;text-transform:uppercase;opacity:.75">AIML Compute</div><h1 style="margin:7px 0 0;font-size:24px">Your GPU access is ready</h1></td></tr>
        <tr><td style="padding:28px"><p style="margin:0 0 22px;color:#617783">Use the credentials below during your confirmed reservation window.</p>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px;background:#e5f6ff;border:1px solid #9bdcff"><tr><td style="padding:15px 17px"><strong style="display:block;font-size:16px">{escape(reservation_date)}</strong><span style="color:#356b89">{escape(reservation_time)}</span></td></tr></table>
        <div style="margin-bottom:7px;font-size:11px;font-weight:bold;letter-spacing:1px;text-transform:uppercase;color:#617783">SSH command</div><pre style="margin:0 0 22px;padding:15px;overflow:auto;background:#102532;color:#ffffff;border-radius:3px;font-family:'JetBrains Mono','SFMono-Regular',Consolas,monospace;font-size:14px;line-height:1.5;white-space:pre-wrap"><span style="color:#ffffff;text-decoration:none">{command_html}</span></pre>
        <div style="margin-bottom:7px;font-size:11px;font-weight:bold;letter-spacing:1px;text-transform:uppercase;color:#617783">Password</div><pre style="margin:0;padding:15px;overflow:auto;background:#edf7fc;color:#102532;border:1px solid #b7cedb;border-radius:3px;font-family:'JetBrains Mono','SFMono-Regular',Consolas,monospace;font-size:16px;line-height:1.5;white-space:pre-wrap">{escape(password)}</pre>
        <p style="margin:22px 0 0;color:#617783;font-size:12px">This password is unique to this reservation. You will receive a different password for every future reservation.</p>
        </td></tr></table></td></tr></table></body></html>""",
        subtype="html",
    )
    _deliver(message)
