#!/bin/bash

if ! id "$TEAM_NAME" >/dev/null 2>&1; then
    useradd -M -d "/home/$TEAM_NAME" -s /bin/bash "$TEAM_NAME"
fi

if [[ ! "${WORKSPACE_GB:-}" =~ ^[1-9][0-9]*$ || ! "${TEMP_STORAGE_GB:-}" =~ ^[1-9][0-9]*$ ]]; then
    echo "Invalid container storage allocation" >&2
    exit 1
fi
printf 'OPENGPU_WORKSPACE_GB=%q\nOPENGPU_TEMP_STORAGE_GB=%q\n' \
    "$WORKSPACE_GB" "$TEMP_STORAGE_GB" > /etc/opengpu-storage.env
chmod 0644 /etc/opengpu-storage.env

# Keep SSH startup focused on the Cynaptics workspace banner instead of the
# distribution MOTD and last-login notice.
touch "/home/$TEAM_NAME/.hushlogin"
chown "$TEAM_NAME:$TEAM_NAME" "/home/$TEAM_NAME" "/home/$TEAM_NAME/.hushlogin"

echo "$TEAM_NAME:$TEAM_PASSWORD_HASH" | chpasswd -e

echo "$TEAM_NAME ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/$TEAM_NAME"
chmod 440 "/etc/sudoers.d/$TEAM_NAME"

chown "$TEAM_NAME:$TEAM_NAME" /workspace
if [[ "$(stat -c '%a' /tmp 2>/dev/null || true)" != "1777" ]]; then
    chmod 1777 /tmp
fi

# Host keys live in a dedicated root-owned host directory so they are unique per user
# and remain stable when the application recreates the container.
install -d -m 700 -o root -g root /etc/ssh/host_keys
if [[ ! -s /etc/ssh/host_keys/ssh_host_ed25519_key ]]; then
    ssh-keygen -q -t ed25519 -N '' -f /etc/ssh/host_keys/ssh_host_ed25519_key
fi
if [[ ! -s /etc/ssh/host_keys/ssh_host_ecdsa_key ]]; then
    ssh-keygen -q -t ecdsa -b 521 -N '' -f /etc/ssh/host_keys/ssh_host_ecdsa_key
fi
if [[ ! -s /etc/ssh/host_keys/ssh_host_rsa_key ]]; then
    ssh-keygen -q -t rsa -b 3072 -N '' -f /etc/ssh/host_keys/ssh_host_rsa_key
fi
chmod 600 /etc/ssh/host_keys/ssh_host_*_key
chmod 644 /etc/ssh/host_keys/ssh_host_*_key.pub

exec /usr/sbin/sshd -D -e
