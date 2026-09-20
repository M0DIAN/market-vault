"""Dependency readiness only; no L4 runtime or trust authority is introduced."""

from importlib.metadata import version
from pathlib import Path
import re
import tomllib

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


ROOT = Path(__file__).resolve().parents[1]

# RFC 8032 section 7.1, TEST 1; public verification material only.
# https://www.rfc-editor.org/rfc/rfc8032.html#section-7.1
PUBLIC_KEY = bytes.fromhex(
    "d75a980182b10ab7d54bfed3c964073a"
    "0ee172f3daa62325af021a68f707511a"
)
MESSAGE = b""
SIGNATURE = bytes.fromhex(
    "e5564300c360ac729086e2cc806e828a"
    "84877f1eb8e5d974d873e06522490155"
    "5fb8821590a33bacc61e39701cf9b46b"
    "d25bf5f0595bbe24655141438e7a100b"
)


def test_crypto_backend_is_an_exact_direct_runtime_dependency():
    with (ROOT / "pyproject.toml").open("rb") as stream:
        dependencies = tomllib.load(stream)["project"]["dependencies"]
    crypto_dependencies = [
        dependency
        for dependency in dependencies
        if re.match(
            r"cryptography(?=$|[\s<>=!~;\[@])",
            dependency.lstrip(),
            re.IGNORECASE,
        )
    ]
    assert crypto_dependencies == ["cryptography==50.0.1"]


def test_crypto_backend_installed_version():
    assert version("cryptography") == "50.0.1"


def test_ed25519_rfc8032_verification_vector():
    public_key = Ed25519PublicKey.from_public_bytes(PUBLIC_KEY)
    assert public_key.verify(SIGNATURE, MESSAGE) is None


def test_ed25519_rejects_one_byte_signature_mutation():
    public_key = Ed25519PublicKey.from_public_bytes(PUBLIC_KEY)
    invalid_signature = SIGNATURE[:-1] + bytes([SIGNATURE[-1] ^ 1])
    with pytest.raises(InvalidSignature):
        public_key.verify(invalid_signature, MESSAGE)


@pytest.mark.parametrize("public_key", [PUBLIC_KEY[:-1], PUBLIC_KEY + b"\x00"])
def test_ed25519_rejects_invalid_public_key_length(public_key):
    with pytest.raises(ValueError):
        Ed25519PublicKey.from_public_bytes(public_key)
