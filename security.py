import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from config import settings


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
