from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


@lru_cache
def _cipher() -> Fernet:
    return Fernet(settings.credential_encryption_key.encode())


def encrypt(plaintext: str) -> str:
    """Encrypt a device credential before it is written to the database."""
    return _cipher().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    try:
        return _cipher().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("stored credential could not be decrypted; encryption key changed?") from exc
