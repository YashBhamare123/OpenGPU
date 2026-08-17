import base64
import binascii
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from config import settings


ALLOWED_SSH_KEY_TYPES = frozenset({
    "ssh-ed25519",
    "ssh-rsa",
    "ecdsa-sha2-nistp256",
    "ecdsa-sha2-nistp384",
    "ecdsa-sha2-nistp521",
    "sk-ssh-ed25519@openssh.com",
    "sk-ecdsa-sha2-nistp256@openssh.com",
})
MAX_SSH_PUBLIC_KEY_BYTES = 8192


class InvalidSshPublicKey(ValueError):
    pass


def normalize_email(value: str) -> str:
    return value.strip().casefold()


def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def verify_secret(value: str, digest: str) -> bool:
    return hmac.compare_digest(hash_secret(value), digest)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def otp_expiry() -> datetime:
    return utcnow() + timedelta(minutes=settings.otp_minutes)


def session_expiry() -> datetime:
    return utcnow() + timedelta(hours=settings.session_hours)


def parse_ssh_public_key(value: str) -> str:
    if value is None or not str(value).strip():
        raise InvalidSshPublicKey("SSH public key is required")
    if len(value) > MAX_SSH_PUBLIC_KEY_BYTES:
        raise InvalidSshPublicKey("SSH public key is too large")
    stripped = value.strip()
    if "-----BEGIN" in stripped or "PRIVATE KEY" in stripped:
        raise InvalidSshPublicKey("Private keys are not accepted")
    if "\n" in stripped or "\r" in stripped:
        raise InvalidSshPublicKey("SSH public key must be a single line")
    parts = stripped.split()
    if len(parts) < 2:
        raise InvalidSshPublicKey("SSH public key is invalid")
    key_type, blob = parts[0], parts[1]
    if "=" in key_type or key_type not in ALLOWED_SSH_KEY_TYPES:
        raise InvalidSshPublicKey("Unsupported SSH public key type")
    padded = blob + ("=" * (-len(blob) % 4))
    try:
        decoded = base64.b64decode(padded, validate=True)
    except binascii.Error as exc:
        raise InvalidSshPublicKey("SSH public key is invalid") from exc
    if not decoded:
        raise InvalidSshPublicKey("SSH public key is invalid")
    comment = " ".join(parts[2:])
    canonical = f"{key_type} {blob}"
    if comment:
        canonical += f" {comment}"
    return canonical


def ssh_public_key_fingerprint(canonical: str) -> str:
    blob = canonical.split()[1]
    padded = blob + ("=" * (-len(blob) % 4))
    digest = hashlib.sha256(base64.b64decode(padded)).digest()
    return "SHA256:" + base64.b64encode(digest).decode().rstrip("=")


def ssh_public_key_comment(canonical: str) -> str | None:
    parts = canonical.split(None, 2)
    return parts[2] if len(parts) > 2 else None


def ssh_key_public_view(canonical: str | None) -> dict | None:
    if not canonical:
        return None
    return {
        "fingerprint": ssh_public_key_fingerprint(canonical),
        "comment": ssh_public_key_comment(canonical),
    }
