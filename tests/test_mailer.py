from dataclasses import replace

import mailer


def test_otp_email_has_plain_and_professional_html_alternatives(monkeypatch):
    captured = []
    monkeypatch.setattr(mailer, "settings", replace(mailer.settings, otp_minutes=10))
    monkeypatch.setattr(mailer, "_deliver", captured.append)

    mailer.send_otp("person@example.edu", "123456")

    assert len(captured) == 1
    message = captured[0]
    assert message["To"] == "person@example.edu"
    assert message["Subject"] == "Your GPU Compute login code"
    assert "123456" not in message["Subject"]
    assert message.is_multipart()
    plain = message.get_body(preferencelist=("plain",)).get_content()
    html = message.get_body(preferencelist=("html",)).get_content()
    assert "123456" in plain
    assert "expires in 10 minutes" in plain.lower()
    assert "123456" in html
    assert "JetBrains Mono" in html
    assert "#25B5FF" in html
    assert "border-left" not in html
