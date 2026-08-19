# Onboarding

OpenGPU has two admission modes. The scheduler, reservation rules, containers, storage, and SSH-key install path are the same in both. Only how a user is admitted changes.

## Lab

The operator chooses Lab mode and SMTP on the setup pages, then the institutional email allowlist. Users open the web UI, verify an approved email with a one-time code, add an SSH public key on first login, and book GPU time on the shared calendar. OpenGPU installs that public key into the user's container when a reservation starts. It does not generate or email SSH passwords.

## Personal

The owner does not configure SMTP or networking by hand. Setup offers Tailscale Funnel for the UI and the SSH gateway. To share the GPU:

```bash
opengpu share alice
```

That prints a time-limited claim URL. Alice opens it, confirms her handle, pastes her SSH public key, and is remembered on that browser. She then uses the same calendar. The owner can also book for her:

```bash
opengpu reserve alice --start 2026-08-18T09:00:00+05:30 --minutes 120
opengpu revoke alice
```

`revoke` disables the user, cancels future reservations, drops sessions, and removes SSH authorization. `/workspace` data is not deleted.

## SSH

Connect through the advertised gateway when a reservation is active:

```bash
ssh <handle-or-username>@<host> -p <ssh-port>
```

Authentication is the public key stored on the user record.
