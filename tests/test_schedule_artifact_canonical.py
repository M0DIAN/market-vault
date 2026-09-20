"""Pure L4 encoding and direct side-effect-boundary regressions."""

import ast
import json
from pathlib import Path

import pytest

from market_vault import schedule_artifact
from market_vault.schedule_artifact._canonical import (
    _canonical_json,
    _decode_base64,
    _encode_base64,
    _parse_canonical_json,
)


def test_canonical_json_known_bytes_nested_sorted_ascii_and_one_lf():
    value = {"z": [None, True, 1, {"\u00e9": "value"}], "a": "US"}
    expected = b'{"a":"US","z":[null,true,1,{"\\u00e9":"value"}]}\n'
    assert _canonical_json(value) == expected
    assert _canonical_json(dict(reversed(list(value.items())))) == expected
    assert _parse_canonical_json(expected) == value
    assert expected.count(b"\n") == 1


@pytest.mark.parametrize("value,encoded", [
    (None, b"null\n"), (True, b"true\n"), (False, b"false\n"),
    (1, b"1\n"), (-1, b"-1\n"), ("", b'""\n'),
    ([], b"[]\n"), ({}, b"{}\n"),
    ("\U0001f600", b'"\\ud83d\\ude00"\n'),
])
def test_canonical_json_domain_roundtrip(value, encoded):
    assert _canonical_json(value) == encoded
    decoded = _parse_canonical_json(encoded)
    assert type(decoded) is type(value)
    assert decoded == value


def test_canonical_json_bool_int_distinct_without_input_mutation():
    value = [True, 1, False, 0]
    assert _canonical_json(value) == b"[true,1,false,0]\n"
    decoded = _parse_canonical_json(_canonical_json(value))
    assert [type(member) for member in decoded] == [bool, int, bool, int]
    assert [type(member) for member in value] == [bool, int, bool, int]


@pytest.mark.parametrize("value", [
    0.0, -0.0, 1.5, float("nan"), float("inf"), -float("inf"),
    b"value", bytearray(b"value"), (1,), {1}, object(),
    {1: "value"}, {True: "value"}, {"nested": [1.0]},
    type("IntSubclass", (int,), {})(1),
    type("StringSubclass", (str,), {})("text"),
    type("ListSubclass", (list,), {})([1]),
    type("DictSubclass", (dict,), {})({"a": 1}),
])
def test_canonical_json_rejects_non_domain_types(value):
    with pytest.raises(TypeError):
        _canonical_json(value)


@pytest.mark.parametrize("text", [
    "e\u0301", "\x00", "\n", "\t", "\x1e", "\x1f",
    "\x7f", "\x80", "\x9f", "unsafe|separator", "\ud800",
])
@pytest.mark.parametrize("as_key", [False, True])
def test_canonical_json_rejects_unsafe_or_non_nfc_keys_and_values(text, as_key):
    value = {text: "ok"} if as_key else {"key": text}
    with pytest.raises(ValueError):
        _canonical_json(value)
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True) + "\n").encode("ascii")
    with pytest.raises(ValueError):
        _parse_canonical_json(raw)


@pytest.mark.parametrize("raw", [
    b"\xef\xbb\xbf{}\n", b'"\xff"\n',
    b'{"a":1,"a":2}\n', b'{"outer":{"a":1,"a":1}}\n',
    b'{"a":1,"\\u0061":1}\n',
    b" {}\n", b"{}\t\n", b"{} \n", b"{}", b"{}\n\n", b"{}\r\n",
    b'{"z":1,"a":2}\n', b'{"a": 1}\n',
    b'"\\u0061"\n', b'"\\/"\n', b'"\xc3\xa9"\n', b'"\\u00E9"\n',
    b"1.0\n", b"1e0\n", b"NaN\n", b"Infinity\n", b"-Infinity\n",
    b"-0\n", b"01\n", b"{}\n{}\n", b"", b'{"a":}\n',
])
def test_canonical_json_parser_rejects_noncanonical_bytes(raw):
    with pytest.raises(ValueError):
        _parse_canonical_json(raw)


@pytest.mark.parametrize("raw", ["{}\n", bytearray(b"{}\n"), memoryview(b"{}\n"),
                                 type("BytesSubclass", (bytes,), {})(b"{}\n")])
def test_canonical_json_parser_requires_exact_bytes(raw):
    with pytest.raises(TypeError):
        _parse_canonical_json(raw)


@pytest.mark.parametrize("kind", [list, dict])
def test_canonical_json_rejects_cycles_but_allows_shared_values(kind):
    value = kind()
    if kind is list:
        value.append(value)
    else:
        value["self"] = value
    with pytest.raises(ValueError, match="cyclic"):
        _canonical_json(value)
    shared = [1]
    assert _canonical_json([shared, shared]) == b"[[1],[1]]\n"


@pytest.mark.parametrize("raw,text", [
    (b"", ""), (b"f", "Zg=="), (b"fo", "Zm8="), (b"foo", "Zm9v"),
    (b"\xfb\xff", "+/8="), (b"\x00\xff", "AP8="),
    (b"e\xcc\x81", "ZcyB"),
])
def test_canonical_base64_known_roundtrip_preserves_raw_bytes(raw, text):
    assert _encode_base64(raw) == text
    assert _decode_base64(text) == raw


@pytest.mark.parametrize("text", [
    "Zg", "Zg=", " Zg==", "Zg==\n", "Z g==", "Zg==\t",
    "-_8=", "+_8=", "Zh==", "Zm9=", "Zg===", "Zm9v=", "====",
    "Zg==AA==", "\u00e9===", "Zg!!",
])
def test_canonical_base64_rejects_noncanonical_input(text):
    with pytest.raises(ValueError):
        _decode_base64(text)


@pytest.mark.parametrize("value", [b"Zg==", bytearray(b"Zg=="), None,
                                    type("StrSubclass", (str,), {})("Zg==")])
def test_canonical_base64_decode_requires_exact_text(value):
    with pytest.raises(TypeError):
        _decode_base64(value)


@pytest.mark.parametrize("value", ["f", bytearray(b"f"), memoryview(b"f"),
                                    type("BytesSubclass", (bytes,), {})(b"f")])
def test_canonical_base64_encode_requires_exact_bytes(value):
    with pytest.raises(TypeError):
        _encode_base64(value)


def test_pure_core_has_closed_imports_and_no_side_effect_apis():
    root = Path(__file__).resolve().parents[1] / "src/market_vault/schedule_artifact"
    expected = {
        "__init__.py", "_canonical.py", "_crypto.py", "_identity.py", "_errors.py",
        "_models.py", "_schema.py", "_semantics.py", "_trust.py",
    }
    assert {path.name for path in root.glob("*.py")} == expected
    allowed_imports = {
        (0, "base64"), (0, "json"), (0, "unicodedata"), (0, "hashlib"),
        (2, "dataset.encoding"), (1, "_canonical"),
        (0, "cryptography.hazmat.primitives.asymmetric.ed25519"),
        (0, "dataclasses"), (0, "datetime"), (0, "types"), (0, "re"),
        (1, "_errors"), (1, "_models"), (1, "_identity"), (1, "_schema"),
        (2, "cross_day.schedule"), (2, "cross_day.identity"),
    }
    allowed_symbols = {
        (2, "dataset.encoding"): {"reject_unsafe_text", "encode_identity"},
        (1, "_canonical"): {"_canonical_json", "_decode_base64", "_parse_canonical_json"},
        (0, "cryptography.hazmat.primitives.asymmetric.ed25519"):
            {"Ed25519PublicKey"},
        (0, "dataclasses"): {"dataclass"},
        (0, "datetime"): {"date", "datetime"},
        (0, "types"): {"MappingProxyType"},
        (1, "_errors"): {"_ScheduleArtifactError", "_require"},
        (1, "_models"): {
            "_ParsedDocument", "_freeze", "_thaw", "_SemanticFacts",
            "_MAX_CIVIL_DATES", "_MAX_SOURCE_RECORDS",
        },
        (1, "_identity"): {"_identity", "_sha256"},
        (1, "_schema"): {"_OUTPUT_ROLES", "_date", "_instant", "_parse_document"},
        (2, "cross_day.schedule"): {"TradingDayRecord", "verify_trading_day_schedule"},
        (2, "cross_day.identity"): {"schedule_pin_id"},
    }
    forbidden = {
        "pathlib", "os", "shutil", "socket", "requests", "urllib", "moomoo",
        "open", "Path", "now", "utcnow", "time", "sleep", "eval", "exec",
        "compile", "__import__", "import_module", "getattr", "globals", "locals",
        "Ed25519PrivateKey", "sign", "generate",
    }
    for name in sorted(expected):
        tree = ast.parse((root / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all((0, alias.name) in allowed_imports for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert (node.level, node.module) in allowed_imports
                assert {alias.name for alias in node.names} <= allowed_symbols[
                    (node.level, node.module)
                ]
            elif isinstance(node, ast.Name):
                assert node.id not in forbidden
            elif isinstance(node, ast.Attribute):
                assert node.attr not in forbidden
    assert schedule_artifact.__all__ == ()
