from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from ..config import get_settings


class SecretEncryptionError(RuntimeError):
    """Raised when `settings_encryption_key` is missing or a ciphertext is invalid.

    Kept generic (mirrors `InvalidLicenseError`'s posture) so callers don't
    need to distinguish "not configured" from "corrupt ciphertext" -- both
    mean the secret can't be recovered right now.
    """


def _fernet() -> Fernet:
    key = get_settings().settings_encryption_key
    if not key:
        raise SecretEncryptionError(
            "SETTINGS_ENCRYPTION_KEY is not configured on this deployment."
        )
    return Fernet(key.encode("utf-8"))


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise SecretEncryptionError("Stored secret could not be decrypted.") from exc
