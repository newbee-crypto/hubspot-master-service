"""
Encryption utility (§10.10).
Fernet-based symmetric encryption for any sensitive config blob that must be stored at rest.
"""

import base64
import logging
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


class Encrypter:
    """
    Fernet symmetric encryption utility.

    Used to encrypt sensitive data (e.g., refresh tokens) before storing at rest.
    The encryption key should be provided via environment variable, never hard-coded.
    """

    def __init__(self, key: Optional[str] = None):
        """
        Initialize with an encryption key.

        Args:
            key: A Fernet-compatible key (base64-encoded 32-byte key).
                 If not provided, a new one will be generated (for development only).
        """
        if key:
            self._fernet = Fernet(key.encode() if isinstance(key, str) else key)
        else:
            logger.warning("No encryption key provided — generating ephemeral key (not suitable for production)")
            self._fernet = Fernet(Fernet.generate_key())

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a plaintext string.

        Returns base64-encoded ciphertext string.
        """
        if not plaintext:
            return ""
        token = self._fernet.encrypt(plaintext.encode("utf-8"))
        return token.decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt a ciphertext string.

        Returns the original plaintext. Raises ValueError on invalid token.
        """
        if not ciphertext:
            return ""
        try:
            plaintext = self._fernet.decrypt(ciphertext.encode("utf-8"))
            return plaintext.decode("utf-8")
        except InvalidToken:
            raise ValueError("Failed to decrypt: invalid token or wrong key")

    @staticmethod
    def generate_key() -> str:
        """Generate a new Fernet encryption key. Store it securely."""
        return Fernet.generate_key().decode("utf-8")
