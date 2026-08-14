from dataclasses import replace
from datetime import datetime, timedelta, timezone

import mailer


def test_otp_email_has_plain_and_professional_html_alternatives(monkeypatch):
    captured = []
    monkeypatch.setattr(mailer, "settings", replace(mailer.settings, otp_minutes=10,
                                                    smtp_from="OpenGPU <opengpu@example.edu>"))
    monkeypatch.setattr(mailer, "_deliver", captured.append)

    mailer.send_otp("person@example.edu", "123456")

    assert len(captured) == 1
    message = captured[0]
    assert message["To"] == "person@example.edu"
    assert message["Subject"] == "Your sign-in code"
    assert "123456" not in message["Subject"]
    assert message.is_multipart()
    plain = message.get_body(preferencelist=("plain",)).get_content()
    html = message.get_body(preferencelist=("html",)).get_content()
    assert "123456" in plain
    assert "expires in 10 minutes" in plain.lower()
    assert "123456" in html
    assert "JetBrains Mono" in html
    assert "#25B5FF" in html
    assert "Cynaptics OpenGPU" in plain
    assert "Cynaptics OpenGPU" in html
    assert '<meta name="viewport"' in html
    assert "display:none" in html
    assert "border-left" not in html
    assert message["From"] == "OpenGPU <opengpu@example.edu>"
    assert message["Date"]
    assert message["Message-ID"].endswith("@example.edu>")
    assert message["Auto-Submitted"] == "auto-generated"
    assert message["X-Auto-Response-Suppress"] == "All"


def test_credentials_and_cancellation_share_transactional_headers_and_template(monkeypatch):
    captured = []
    monkeypatch.setattr(mailer, "settings", replace(
        mailer.settings, smtp_from="OpenGPU <opengpu@example.edu>", server_ip="gpu.example.edu"
    ))
    monkeypatch.setattr(mailer, "_deliver", captured.append)
    start = datetime(2026, 7, 28, 10, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=2)

    mailer.send_credentials("person@example.edu", "gpu1", "secret", 22001, start, end)
    mailer.send_cancellation("person@example.edu", start, end)

    assert len(captured) == 2
    for message in captured:
        assert message.is_multipart()
        assert message["From"] == "OpenGPU <opengpu@example.edu>"
        assert message["Date"]
        assert message["Message-ID"].endswith("@example.edu>")
        assert message["Auto-Submitted"] == "auto-generated"
        assert message["X-Auto-Response-Suppress"] == "All"
        assert "#25B5FF" in message.get_body(preferencelist=("html",)).get_content()
    cancellation = captured[1]
    assert "reservation cancelled" in cancellation["Subject"].lower()
    assert "has been cancelled" in cancellation.get_body(preferencelist=("plain",)).get_content()
