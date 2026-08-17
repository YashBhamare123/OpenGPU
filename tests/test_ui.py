from ui import banner, format_checks, panel


class Check:
    def __init__(self, name, ok, detail, fatal=True):
        self.name = name
        self.ok = ok
        self.detail = detail
        self.fatal = fatal


def test_banner_includes_wordmarks():
    text = banner()
    assert "OPENGPU" in text or "██████" in text


def test_panel_is_plain_without_tty():
    text = panel("Share link", ["https://example/claim/token"])
    assert "Share link" in text
    assert "claim/token" in text


def test_format_checks_keeps_stable_labels():
    report = format_checks(
        [
            Check("docker", True, "ok"),
            Check("workspace", False, "low disk", fatal=False),
            Check("nvidia", False, "missing driver"),
        ]
    )
    assert "ok    docker:" in report
    assert "warn  workspace:" in report
    assert "fail  nvidia:" in report
