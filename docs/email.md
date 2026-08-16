# Email

OpenGPU uses SMTP with STARTTLS for three transactional messages: login OTPs, reservation SSH credentials, and cancellation confirmations. Skip `SMTP_HOST` during setup to run without a relay: self-service booking is disabled, only administrators can request login codes (printed on the host terminal), and SSH passwords print there for sharing instead of being emailed.

## Login codes

The OTP email includes matching plain-text and professionally formatted HTML alternatives, with a copy-friendly one-time-code block and explicit expiry guidance. The request endpoint suppresses SMTP errors; its approval status lets the frontend direct unapproved users to the administrator.

Codes are six digits, stored only as hashes, expire according to `OTP_MINUTES`, and are limited by attempts and hourly issuance.

## Reservation credentials

Each successful reservation provisioning sends multipart plain-text and HTML email containing:

- Reservation date and time
- Exact SSH command
- Reservation-specific password
- Notice that the next reservation receives a different password

The HTML separates the username, `@`, and host into elements to discourage mail clients from converting the SSH target into an email hyperlink. Command and password blocks use a monospaced font stack.

Plaintext passwords exist only during provisioning and SMTP delivery. They must not be logged, persisted, placed in audit details, or included in exception messages. If delivery fails, the associated container is removed so a retry cannot leave an unknown password active.

## Cancellation confirmations

User and administrator cancellations send the reservation owner matching plain-text and branded HTML alternatives with the cancelled date and time. Cancellation remains committed if SMTP is temporarily unavailable.

## Deliverability

All three message types use a consistent Cynaptics OpenGPU identity and factual subject line, a purpose-specific preheader, semantic HTML metadata, a restrained transactional footer, and RFC-style `Date`, unique `Message-ID`, `Auto-Submitted`, and automatic-response-suppression headers. They are transactional rather than promotional, so they do not include misleading list-unsubscribe headers.

Headers and templates cannot guarantee inbox placement. The domain in `SMTP_FROM` must align with the relay's authenticated sending domain. Configure SPF, DKIM, and DMARC for that domain, ensure the relay has valid forward and reverse DNS, retain TLS, and monitor rejection and complaint rates. Use a dedicated transactional sender address and do not send unrelated bulk mail through it.

## Configuration and testing

Required settings for email are `SMTP_HOST`, `SMTP_PORT`, and `SMTP_FROM`; authenticated relays also require `SMTP_USER` and `SMTP_PASSWORD`. Leave `SMTP_HOST` empty to skip email. Credentials belong only in the mode-600 environment file or service secret mechanism. Do not log OTPs or plaintext passwords; the serve process stdout is the operator share channel when SMTP is off.

Test mail changes against a dedicated recipient and relay. Verify both MIME alternatives, escaping of user-controlled values, copyability of SSH data, mobile rendering, and failure behavior. Never use a production user's reservation to test template changes.
