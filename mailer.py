import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime, formataddr, make_msgid, parseaddr
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


def _message(recipient: str, subject: str) -> EmailMessage:
    message = EmailMessage()
    sender_name, sender_address = parseaddr(settings.smtp_from)
    message["Subject"] = subject
    message["From"] = formataddr((sender_name or "Cynaptics OpenGPU", sender_address))
    message["To"] = recipient
    message["Date"] = format_datetime(datetime.now(timezone.utc))
    message["Message-ID"] = make_msgid(domain=sender_address.rsplit("@", 1)[-1] if "@" in sender_address else None)
    message["Auto-Submitted"] = "auto-generated"
    message["X-Auto-Response-Suppress"] = "All"
    return message


def send_email(recipient: str, subject: str, body: str) -> None:
    message = _message(recipient, subject)
    message.set_content(body)
    _deliver(message)


def send_otp(email: str, code: str) -> None:
    plain = (
        "Your login code\n\n"
        f"{code}\n\n"
        f"This code expires in {settings.otp_minutes} minutes and can only be used once.\n"
        "If you did not request this code, ignore this email.\n\n"
        "This automated account-security message was sent by Cynaptics OpenGPU.\n"
    )
    message = _message(email, "Your sign-in code")
    message.set_content(plain)
    message.add_alternative(
        f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Cynaptics OpenGPU sign-in code</title></head><body style="margin:0;background:#f3f9fc;color:#102532;font-family:Arial,sans-serif">
        <div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent">Your requested Cynaptics OpenGPU sign-in code expires in {settings.otp_minutes} minutes.</div>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:32px 16px">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:620px;background:#ffffff;border:1px solid #d5e3eb">
        <tr><td style="padding:24px 28px;background:#25B5FF;color:#102532"><div style="font-size:11px;letter-spacing:1.5px;text-transform:uppercase;opacity:.75">Cynaptics OpenGPU</div><h1 style="margin:7px 0 0;font-size:24px">Sign-in code</h1></td></tr>
        <tr><td style="padding:28px"><p style="margin:0 0 22px;color:#617783">Enter this code to sign in.</p>
        <div style="margin-bottom:7px;font-size:11px;font-weight:bold;letter-spacing:1px;text-transform:uppercase;color:#617783">Login code</div>
        <pre style="margin:0;padding:20px;overflow:auto;background:#102532;color:#ffffff;border-radius:3px;text-align:center;font-family:'JetBrains Mono','SFMono-Regular',Consolas,monospace;font-size:30px;font-weight:700;line-height:1.25;letter-spacing:8px;white-space:pre-wrap">{escape(code)}</pre>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:22px;background:#e5f6ff;border:1px solid #9bdcff"><tr><td style="padding:15px 17px"><strong style="display:block;font-size:14px">Expires in {settings.otp_minutes} minutes</strong><span style="color:#356b89;font-size:12px">Single use. Do not share it.</span></td></tr></table>
        <p style="margin:22px 0 0;color:#617783;font-size:12px">If you did not request this code, ignore this email.</p><p style="margin:12px 0 0;color:#8a9ca6;font-size:11px">Automated account-security message from Cynaptics OpenGPU.</p>
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
        reservation_time = "See OpenGPU for timing"
        schedule_text = ""

    plain = (
        "Your SSH access is ready.\n\n"
        f"{schedule_text}"
        f"SSH command:\n{command}\n\n"
        f"Password:\n{password}\n\n"
        "This password is valid only for this reservation.\n\n"
        "This automated reservation message was sent by Cynaptics OpenGPU.\n"
    )
    message = _message(email, f"SSH access for {reservation_date}")
    message.set_content(plain)
    message.add_alternative(
        f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Cynaptics OpenGPU SSH access</title></head><body style="margin:0;background:#f3f9fc;color:#102532;font-family:Arial,sans-serif">
        <div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent">SSH access details for your scheduled Cynaptics OpenGPU reservation.</div>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:32px 16px">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:620px;background:#ffffff;border:1px solid #d5e3eb">
        <tr><td style="padding:24px 28px;background:#25B5FF;color:#102532"><div style="font-size:11px;letter-spacing:1.5px;text-transform:uppercase;opacity:.75">Cynaptics OpenGPU</div><h1 style="margin:7px 0 0;font-size:24px">SSH access</h1></td></tr>
        <tr><td style="padding:28px"><p style="margin:0 0 22px;color:#617783">Credentials for your reservation:</p>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px;background:#e5f6ff;border:1px solid #9bdcff"><tr><td style="padding:15px 17px"><strong style="display:block;font-size:16px">{escape(reservation_date)}</strong><span style="color:#356b89">{escape(reservation_time)}</span></td></tr></table>
        <div style="margin-bottom:7px;font-size:11px;font-weight:bold;letter-spacing:1px;text-transform:uppercase;color:#617783">SSH command</div><pre style="margin:0 0 22px;padding:15px;overflow:auto;background:#102532;color:#ffffff;border-radius:3px;font-family:'JetBrains Mono','SFMono-Regular',Consolas,monospace;font-size:14px;line-height:1.5;white-space:pre-wrap"><span style="color:#ffffff;text-decoration:none">{command_html}</span></pre>
        <div style="margin-bottom:7px;font-size:11px;font-weight:bold;letter-spacing:1px;text-transform:uppercase;color:#617783">Password</div><pre style="margin:0;padding:15px;overflow:auto;background:#edf7fc;color:#102532;border:1px solid #b7cedb;border-radius:3px;font-family:'JetBrains Mono','SFMono-Regular',Consolas,monospace;font-size:16px;line-height:1.5;white-space:pre-wrap">{escape(password)}</pre>
        <p style="margin:22px 0 0;color:#617783;font-size:12px">This password is valid only for this reservation.</p><p style="margin:12px 0 0;color:#8a9ca6;font-size:11px">Automated reservation message from Cynaptics OpenGPU.</p>
        </td></tr></table></td></tr></table></body></html>""",
        subtype="html",
    )
    _deliver(message)


def send_cancellation(email: str, reservation_start: datetime,
                      reservation_end: datetime) -> None:
    start = reservation_start.astimezone()
    end = reservation_end.astimezone()
    reservation_date = start.strftime("%A, %d %B %Y")
    reservation_time = f'{start.strftime("%I:%M %p").lstrip("0")} – {end.strftime("%I:%M %p").lstrip("0")} {start.tzname() or ""}'.strip()
    plain = (
        "Your reservation has been cancelled.\n\n"
        f"Reservation: {reservation_date}, {reservation_time}\n\n"
        "This time is now available for another reservation.\n\n"
        "This automated reservation message was sent by Cynaptics OpenGPU.\n"
    )
    message = _message(email, f"Reservation cancelled for {reservation_date}")
    message.set_content(plain)
    message.add_alternative(
        f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Cynaptics OpenGPU reservation cancelled</title></head><body style="margin:0;background:#f3f9fc;color:#102532;font-family:Arial,sans-serif">
        <div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent">Cancellation confirmation for your Cynaptics OpenGPU reservation.</div>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:32px 16px">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:620px;background:#ffffff;border:1px solid #d5e3eb">
        <tr><td style="padding:24px 28px;background:#25B5FF;color:#102532"><div style="font-size:11px;letter-spacing:1.5px;text-transform:uppercase;opacity:.75">Cynaptics OpenGPU</div><h1 style="margin:7px 0 0;font-size:24px">Reservation cancelled</h1></td></tr>
        <tr><td style="padding:28px"><p style="margin:0 0 22px;color:#617783">Your GPU reservation has been cancelled.</p>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px;background:#e5f6ff;border:1px solid #9bdcff"><tr><td style="padding:15px 17px"><strong style="display:block;font-size:16px">{escape(reservation_date)}</strong><span style="color:#356b89">{escape(reservation_time)}</span></td></tr></table>
        <p style="margin:0;color:#617783;font-size:12px">This time is now available for another reservation.</p><p style="margin:12px 0 0;color:#8a9ca6;font-size:11px">Automated reservation message from Cynaptics OpenGPU.</p>
        </td></tr></table></td></tr></table></body></html>""",
        subtype="html",
    )
    _deliver(message)
