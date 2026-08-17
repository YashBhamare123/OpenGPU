# Scheduler and Containers

The scheduler converts database state into Docker state. It runs independently from the API and must be the only application service with Docker socket access.

## Leadership and loop

At startup, the scheduler obtains PostgreSQL advisory lock `72819431` on a dedicated connection. Failure to acquire it aborts startup. Each loop verifies that connection, processes at most one provisioning job, reconciles containers, records a heartbeat, and waits `POLL_INTERVAL` seconds.

## Provisioning jobs

Jobs are claimed in creation order with row locking and `SKIP LOCKED`. Resource allocation derives stable values from the team ID:

```text
Linux user       gpu<ID>
Container        gpu-user-<ID>
Legacy DB name   gpu-workspace-<ID>
SSH port         next ssh_port_seq value
```

The current storage implementation does not create the legacy-named workspace volume. It derives host paths below `WORKSPACE_ROOT/users/<ID>/`:

```text
workspace.img    loop-mounted at workspace/  -> /workspace
scratch.img      loop-mounted at scratch/
  scratch/home   -> /home/gpu<ID>
  scratch/tmp    -> /tmp
  scratch/etc    -> /etc
ssh-host-keys/   -> /etc/ssh/host_keys
```

`ssh-host-keys/authorized_keys` is written from `teams.ssh_public_key` at provision time and refreshed immediately before the container starts. `sshd` is started with `PubkeyAuthentication=yes` and `AuthorizedKeysFile=/etc/ssh/host_keys/authorized_keys` so a seeded scratch `/etc` cannot keep pubkey login disabled. Password authentication remains enabled.

Before Docker provisioning, the scheduler invokes the narrowly scoped root helper configured by `STORAGE_HELPER`. The helper creates sparse ext4 images, loop-mounts them on the host, and Docker only bind-mounts the resulting directories. Workspace images grow in place and are never shrunk. Scratch disks are sized to the reservation and removed when the user has no current or future booking; the helper also unmounts idle workspace images so loop devices are released. Persistent `/workspace` data remains in `workspace.img`.

User containers use a read-only root filesystem plus `/run` tmpfs. Writable paths are the bind-mounted workspace, home, tmp, a scratch copy of `/etc`, and SSH host keys. That replaces overlay `storage_opt` size caps, which required XFS project quotas.

Provisioning generates a new password and SHA-512-compatible Linux password hash, creates a stopped labelled container, and delivers credentials by email or by printing them on the host when SMTP is skipped. Only the hash is stored. If delivery fails, the incomplete container is removed and scratch storage is released; retry generates a different password.

## Reconciliation

The scheduler computes:

- the one currently active, enabled, ready container that should run;
- every container belonging to a non-cancelled reservation that has not ended;
- all Docker containers carrying the OpenGPU application label.

It then applies these rules:

1. Remove a managed container that has no current or future reservation.
2. Stop a retained future container if it is unexpectedly running.
3. Release leftover scratch disks and unmount idle workspace images for users with no current or future reservation.
4. Start the desired active container if it is not running, remounting its images first.
5. Record each transition in `audit_events`.

Consequently, cancellation and expiry delete the container filesystem. Bind-mounted workspace and host-key directories survive.

## Ownership and safety invariants

- Managed resources require `app=aiml-gpu-reservation` and the expected `aiml.user_id` label.
- A name occupied by an unmanaged resource is an error, never an adoption opportunity.
- Host storage paths are derived only from a positive numeric database ID and an absolute configured root.
- A running provisioning container is not replaced.
- Published SSH ports are probed before creation.
- Containers request one GPU, use configured CPU/memory/PID/shared-memory limits, a read-only root filesystem, and `restart=no`.
- SSH host keys are generated in their persistent bind mount, not baked into the image.

## Changing lifecycle code

Add scheduler tests for desired, future, cancelled, expired, missing, running, and unmanaged container states. Test database behavior separately when changing job selection or desired-state SQL. Never run lifecycle experiments while a real reservation is active.
