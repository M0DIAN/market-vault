"""Ed25519 verification primitive only; a supplied key gains no authority."""

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def _verify_ed25519(public_key_bytes: bytes, message: bytes, signature: bytes) -> None:
    """Verify exact message bytes, propagating backend failures fail-closed."""
    if any(type(value) is not bytes for value in (public_key_bytes, message, signature)):
        raise TypeError("Ed25519 inputs must be exact bytes")
    if len(public_key_bytes) != 32:
        raise ValueError("Ed25519 public key must be exactly 32 bytes")
    if len(signature) != 64:
        raise ValueError("Ed25519 signature must be exactly 64 bytes")
    Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(signature, message)
