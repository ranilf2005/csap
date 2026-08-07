from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import settings

_MAX_BCRYPT_BYTES = 72

# Hashing a throwaway value keeps the unknown-account path as slow as the known
# one, so response time does not reveal which addresses exist.
_DUMMY_HASH = bcrypt.hashpw(b"csap-timing-equaliser", bcrypt.gensalt())


def waste_a_hash() -> None:
    bcrypt.checkpw(b"csap-timing-equaliser", _DUMMY_HASH)


def hash_password(plain: str) -> str:
    # bcrypt silently truncates beyond 72 bytes; reject instead of hiding it.
    if len(plain.encode()) > _MAX_BCRYPT_BYTES:
        raise ValueError("password must be 72 bytes or fewer")
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False


def create_access_token(subject: str, extra_claims: dict[str, Any] | None = None) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
        "iss": "csap",
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(
        token,
        settings.secret_key,
        algorithms=[settings.jwt_algorithm],
        issuer="csap",
        options={"require": ["exp", "iat", "sub"]},
    )
