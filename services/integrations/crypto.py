"""
Credential encryption for the Integration Layer.

Nothing in this module ever stores a plaintext API key/token/password —
integrations.credentials_reference only ever points at a row in
integration_credentials, whose encrypted_value is Fernet-encrypted (AES-128
CBC + HMAC) with a key from the INTEGRATION_CREDENTIALS_KEY env var. The key
itself is never stored in the database or committed to the repo.
"""

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken


class CredentialsKeyMissing(RuntimeError):
    pass


def _fernet() -> Fernet:
    key = os.environ.get("INTEGRATION_CREDENTIALS_KEY", "").strip()
    if not key:
        raise CredentialsKeyMissing(
            "INTEGRATION_CREDENTIALS_KEY is not set — cannot store or read "
            "integration credentials. Generate one with: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    # Accept either a proper Fernet key (32 url-safe base64 bytes) or an
    # arbitrary passphrase, which we derive a valid key from — so a human
    # can set a memorable value in .env without hand-generating base64.
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError):
        derived = base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest())
        return Fernet(derived)


def encrypt_credentials(plaintext: str) -> str:
    """plaintext is typically a JSON string of {field: value} credential pairs."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_credentials(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        raise ValueError("Could not decrypt credentials — wrong key or corrupted value")


def mask_secret(value: str, keep: int = 4) -> str:
    """For UI/log display only — never round-trips back to a real value."""
    if not value:
        return ""
    if len(value) <= keep:
        return "*" * len(value)
    return "*" * (len(value) - keep) + value[-keep:]


def mask_credentials_dict(fields: dict) -> dict:
    return {k: mask_secret(str(v)) if v else v for k, v in fields.items()}
