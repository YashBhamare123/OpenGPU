from pathlib import Path


def test_provisioning_notice_loads_until_ssh_credentials_are_sent():
    javascript = Path("frontend/app.js").read_text()
    stylesheet = Path("frontend/app.css").read_text()

    assert 'A fresh SSH password will be emailed shortly.`,"loading")' in javascript
    assert 'announce("SSH access sent","Check your email for the credentials for this reservation.","success")' in javascript
    assert ".notice.loading .notice-icon::after" in stylesheet
    assert "animation:notice-spin" in stylesheet
    assert ".notice-icon::after{content:'✓'}" in stylesheet
    assert "900-(Date.now()-state.provisioningNoticeAt)" in javascript


def test_frontend_asset_version_is_current():
    html = Path("frontend/index.html").read_text()

    assert 'app.css?v=22' in html
    assert 'app.js?v=22' in html


def test_status_panels_use_thin_left_borders():
    stylesheet = Path("frontend/app.css").read_text()

    assert "border-left-width:1px" in stylesheet
    assert "border-left-width:0" not in stylesheet
