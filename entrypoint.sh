#!/bin/bash

if ! id "$TEAM_NAME" >/dev/null 2>&1; then
    useradd -m -s /bin/bash "$TEAM_NAME"
fi

# Keep SSH startup focused on the Cynaptics workspace banner instead of the
# distribution MOTD and last-login notice.
touch "/home/$TEAM_NAME/.hushlogin"
chown "$TEAM_NAME:$TEAM_NAME" "/home/$TEAM_NAME/.hushlogin"

echo "$TEAM_NAME:$TEAM_PASSWORD_HASH" | chpasswd -e

echo "$TEAM_NAME ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/$TEAM_NAME"
chmod 440 "/etc/sudoers.d/$TEAM_NAME"

mkdir -p /workspace
chown "$TEAM_NAME:$TEAM_NAME" /workspace

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
