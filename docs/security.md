# Security Model

OpenGPU is designed for trusted institutional users sharing one GPU. It hardens control-plane boundaries and resource ownership, but user containers are not a hostile multi-tenant sandbox.

## Trust boundaries

- The browser can request only actions for the authenticated session user.
- The API can access PostgreSQL and SMTP but should not access Docker.
- The scheduler can access PostgreSQL, SMTP, host workspace directories, and the Docker socket.
- Container users receive passwordless sudo inside their own container.
- PostgreSQL is authoritative for reservation ownership and desired state.

## Credentials

- OTPs and browser session tokens are stored only as SHA-256 hashes.
- OTP requests expose only allowlist status and the public `ACCESS_CONTACT_EMAIL`; private `ADMIN_EMAILS` are never returned. Approved users are rate limited and code-verification failures remain generic.
- Session cookies are HTTP-only, SameSite Lax, and configurable as Secure.
- SSH passwords are generated per reservation; only their Linux password hash is retained.
- SMTP and database credentials live outside Git in a mode-600 environment file.
- SSH host private keys are generated per user in a root-owned bind mount and are not baked into the image.

## Resource protection

- Docker operations require exact application and user labels.
- Names occupied by unrelated resources cause failure rather than adoption.
- Workspace paths derive from numeric database IDs under an absolute configured root.
- The API never accepts a container name, workspace path, SSH port, or team ID from reservation input.
- The database enforces overlaps and per-user booking rules under concurrent requests.
- Containers use `restart=no`, so Docker cannot bypass scheduler state after a host restart.

## Network boundary

Terminate browser traffic with HTTPS and restrict the web endpoint and SSH port range to an institutional LAN or VPN. Bind published SSH ports only to the intended private interface. Configure `ALLOWED_ORIGINS` with exact browser origins.

The origin middleware is not a replacement for HTTPS, secure cookies, firewall rules, or host hardening. When no Origin header is present, the middleware allows the request; cookie authentication and network controls remain essential.

## Known limitations

- Passwordless sudo allows a user full control of their container.
- Workspace and scratch capacity are enforced with sized ext4 images. The container root is read-only; passwordless sudo cannot fill the Docker overlay.
- Workspace capacity is enforced, but automatic retention/deletion of idle `workspace.img` files is not yet implemented.
- The shared Docker daemon is a high-privilege dependency.
- Password authentication is weaker than per-reservation SSH certificates or user public keys.
- Application-level OTP issuance is not a distributed edge rate limiter.

Security changes should include tests for authentication boundaries, resource ownership, path validation, database concurrency, and failure cleanup. Never place production credentials or database dumps in issues, logs, fixtures, or commits.
