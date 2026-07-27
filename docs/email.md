# Email

OpenGPU uses SMTP with STARTTLS for two messages: login OTPs and reservation SSH credentials.

## Login codes

OTP email is plain text. The request endpoint suppresses SMTP errors and always returns a generic response so callers cannot enumerate approved addresses or learn mail-server state.

Codes are six digits, stored only as hashes, expire according to `OTP_MINUTES`, and are limited by attempts and hourly issuance.

## Reservation credentials

Each successful reservation provisioning sends multipart plain-text and HTML email containing:

- Reservation date and time
- Exact SSH command
- Reservation-specific password
- Notice that the next reservation receives a different password

The HTML separates the username, `@`, and host into elements to discourage mail clients from converting the SSH target into an email hyperlink. Command and password blocks use a monospaced font stack.

Plaintext passwords exist only during provisioning and SMTP delivery. They must not be logged, persisted, placed in audit details, or included in exception messages. If delivery fails, the associated container is removed so a retry cannot leave an unknown password active.

## Configuration and testing

Required settings are `SMTP_HOST`, `SMTP_PORT`, and `SMTP_FROM`; authenticated relays also require `SMTP_USER` and `SMTP_PASSWORD`. Credentials belong only in the mode-600 environment file or service secret mechanism.

Test mail changes against a dedicated recipient and relay. Verify both MIME alternatives, escaping of user-controlled values, copyability of SSH data, mobile rendering, and failure behavior. Never use a production user's reservation to test template changes.
