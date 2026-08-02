from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path


FORBIDDEN_PARTS = {
    ".venv",
    "data",
    "catalog",
    "manifests",
    "reports",
    "__pycache__",
    ".pytest_cache",
}
FORBIDDEN_PATTERNS = [
    ".env",
    ".env.*",
    "*.duckdb",
    "*.duckdb.wal",
    "*.parquet",
]
CREDENTIAL_FILENAMES = {
    "credentials.json",
    "client_secret.json",
    "secrets.json",
    "service_account.json",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
}
MAX_TRACKED_FILE_BYTES = 10 * 1024 * 1024


def _normalized(path: str) -> str:
    return path.replace("\\", "/").strip("/")


def list_tracked_files(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return [item for item in result.stdout.decode("utf-8").split("\0") if item]


def check_tracked_files(root: Path, tracked_files: list[str]) -> list[str]:
    violations: list[str] = []
    for raw_path in tracked_files:
        path = _normalized(raw_path)
        parts = set(path.split("/"))
        name = Path(path).name
        if parts & FORBIDDEN_PARTS:
            violations.append(f"forbidden tracked path: {path}")
        if any(fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(path, pattern) for pattern in FORBIDDEN_PATTERNS):
            violations.append(f"forbidden tracked file pattern: {path}")
        if name.lower() in CREDENTIAL_FILENAMES:
            violations.append(f"credential-like tracked filename: {path}")

        full_path = root / raw_path
        if full_path.exists() and full_path.is_file() and full_path.stat().st_size > MAX_TRACKED_FILE_BYTES:
            size_mb = full_path.stat().st_size / (1024 * 1024)
            violations.append(f"tracked file exceeds 10 MB: {path} ({size_mb:.1f} MB)")
    return violations


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    violations = check_tracked_files(root, list_tracked_files(root))
    if violations:
        print("Repository hygiene check failed:")
        for item in violations:
            print(f"- {item}")
        return 1
    print("Repository hygiene check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
