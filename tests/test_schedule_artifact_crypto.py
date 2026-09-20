"""RFC 8032 public verification only; no private keys or signing."""

import pytest
from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm

from market_vault.schedule_artifact import _crypto
from market_vault.schedule_artifact._crypto import _verify_ed25519


# RFC 8032 section 7.1 TEST 1 and TEST 2, public material only.
# https://www.rfc-editor.org/rfc/rfc8032.html#section-7.1
VECTORS = (
    (
        bytes.fromhex("d75a980182b10ab7d54bfed3c964073a"
                      "0ee172f3daa62325af021a68f707511a"),
        b"",
        bytes.fromhex("e5564300c360ac729086e2cc806e828a"
                      "84877f1eb8e5d974d873e06522490155"
                      "5fb8821590a33bacc61e39701cf9b46b"
                      "d25bf5f0595bbe24655141438e7a100b"),
    ),
    (
        bytes.fromhex("3d4017c3e843895a92b70aa74d1b7ebc"
                      "9c982ccf2ec4968cc0cd55f12af4660c"),
        bytes.fromhex("72"),
        bytes.fromhex("92a009a9f0d4cab8720e820b5f642540"
                      "a2b27b5416503f8fb3762223ebdb69da"
                      "085ac1e43e15996e458f3613d0f11d8c"
                      "387b2eaeb4302aeeb00d291612bb0c00"),
    ),
)


@pytest.mark.parametrize("key,message,signature", VECTORS)
def test_rfc8032_positive_including_empty_message(key, message, signature):
    assert _verify_ed25519(key, message, signature) is None


@pytest.mark.parametrize("key,message,signature", VECTORS)
def test_invalid_signature_fails_closed(key, message, signature):
    changed = signature[:-1] + bytes([signature[-1] ^ 1])
    with pytest.raises(InvalidSignature):
        _verify_ed25519(key, message, changed)


def test_one_byte_message_mutation_fails_closed():
    key, message, signature = VECTORS[1]
    with pytest.raises(InvalidSignature):
        _verify_ed25519(key, bytes([message[0] ^ 1]), signature)


@pytest.mark.parametrize("position,length", [(0, 31), (0, 33), (2, 63), (2, 65)])
def test_malformed_lengths_fail_before_backend(monkeypatch, position, length):
    class UnreachableBackend:
        @staticmethod
        def from_public_bytes(value):
            pytest.fail("malformed input reached cryptographic backend")

    monkeypatch.setattr(_crypto, "Ed25519PublicKey", UnreachableBackend)
    args = list(VECTORS[0])
    args[position] = b"\x00" * length
    with pytest.raises(ValueError, match="exactly"):
        _verify_ed25519(*args)


@pytest.mark.parametrize("position", [0, 1, 2])
@pytest.mark.parametrize("convert", [bytearray, memoryview,
                                      lambda value: value.hex(),
                                      type("BytesSubclass", (bytes,), {})])
def test_inputs_require_exact_bytes(monkeypatch, position, convert):
    class UnreachableBackend:
        @staticmethod
        def from_public_bytes(value):
            pytest.fail("non-bytes input reached cryptographic backend")

    monkeypatch.setattr(_crypto, "Ed25519PublicKey", UnreachableBackend)
    args = list(VECTORS[0])
    args[position] = convert(args[position])
    with pytest.raises(TypeError, match="exact bytes"):
        _verify_ed25519(*args)


@pytest.mark.parametrize("failure", [UnsupportedAlgorithm("unsupported"),
                                      RuntimeError("backend failure")])
@pytest.mark.parametrize("stage", ["key", "verify"])
def test_backend_failures_propagate_without_fallback(monkeypatch, failure, stage):
    class FailingBackend:
        @staticmethod
        def from_public_bytes(value):
            assert value is VECTORS[1][0]
            if stage == "key":
                raise failure
            return FailingBackend()

        def verify(self, signature, message):
            assert signature is VECTORS[1][2]
            assert message is VECTORS[1][1]
            raise failure

    monkeypatch.setattr(_crypto, "Ed25519PublicKey", FailingBackend)
    with pytest.raises(type(failure)) as caught:
        _verify_ed25519(*VECTORS[1])
    assert caught.value is failure
