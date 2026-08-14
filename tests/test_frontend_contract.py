from pathlib import Path


def test_provisioning_notice_loads_until_ssh_credentials_are_sent():
    javascript = Path("frontend/app.js").read_text()
    stylesheet = Path("frontend/app.css").read_text()

    assert 'Preparing SSH access.`,"loading")' in javascript
    assert 'announce("SSH access sent","Check your email.","success")' in javascript
    assert ".notice.loading .notice-icon::after" in stylesheet
    assert "animation:notice-spin" in stylesheet
    assert ".notice-icon::after{content:'✓'}" in stylesheet
    assert "900-(Date.now()-state.provisioningNoticeAt)" in javascript


def test_status_panels_use_thin_left_borders():
    stylesheet = Path("frontend/app.css").read_text()

    assert "border-left-width:1px" in stylesheet
    assert "border-left-width:0" not in stylesheet


def test_dark_mode_is_shared_and_persistent():
    user_html = Path("frontend/index.html").read_text()
    admin_html = Path("frontend/admin.html").read_text()
    javascript = Path("frontend/theme.js").read_text()
    stylesheet = Path("frontend/app.css").read_text()

    for html in (user_html, admin_html):
        assert 'id="theme-toggle"' in html
        assert "/frontend/theme.js?" in html
        assert "/frontend/app.css?" in html
    assert 'localStorage.getItem("opengpu-theme")' in javascript
    assert 'root.dataset.theme' in javascript
    assert ':root[data-theme="dark"]' in stylesheet


def test_cross_midnight_reservations_are_allowed_and_render_as_continuations():
    javascript = Path("frontend/app.js").read_text()
    stylesheet = Path("frontend/app.css").read_text()

    assert "The session must finish before midnight." not in javascript
    assert 'continues-from-previous' in javascript
    assert 'continues-into-next' in javascript
    assert "reservation-flow" in stylesheet
    assert "day-boundaries" in stylesheet


def test_admin_frontend_has_server_backed_management_controls():
    html = Path("frontend/admin.html").read_text()
    javascript = Path("frontend/admin.js").read_text()

    assert 'id="target-email"' in html
    assert 'id="target-email" type="email"' in html
    assert 'id="whitelist-email"' in html
    assert 'id="allow-extended"' not in html
    assert "allow_extended:allowExtended" in javascript
    assert "selection.end-selection.start>state.reservationLimitMinutes*60*1000" in javascript
    assert 'id="admin-start-time-text"' in html
    assert 'id="admin-duration-value"' in html
    assert 'id="admin-day-strip"' in html
    assert 'id="admin-timeline"' in html
    assert 'id="admin-confirm-dialog"' in html
    assert 'id="admin-cancel-dialog"' in html
    assert 'id="reservation-search"' in html
    assert 'type="datetime-local"' not in html
    assert 'method:"POST"' in javascript
    assert 'method:"DELETE"' in javascript
    assert '"/admin/reservations"' in javascript
    assert '"/admin/users"' in javascript
    assert "reservation.display_name" in javascript
    assert "reservation.email" in javascript
    assert 'event.key==="Tab"' in javascript
    assert 'className="inline-email-ghost"' in javascript
    assert 'attachEmailCompletion($("target-email")' in javascript
    assert 'attachEmailCompletion($("reservation-search")' in javascript
    assert 'attachEmailCompletion($("whitelist-email")' not in javascript
    assert "start.setMinutes(now.getMinutes()+1,0,0)" in javascript
    assert "minutes/1440*100" in javascript


def test_unapproved_login_shows_admin_contact_flow():
    html = Path("frontend/index.html").read_text()
    javascript = Path("frontend/app.js").read_text()

    assert 'id="access-request"' in html
    assert 'id="contact-admin"' in html
    assert 'id="copy-admin-email"' in html
    assert 'class="copy-icon"' in html
    assert 'class="check-icon"' in html
    assert 'id="retry-access"' in html
    assert "data.approved" in javascript
    assert "navigator.clipboard.writeText" in javascript
    assert "mailto:" not in javascript
    assert "2000-(Date.now()-submittedAt)" in javascript
